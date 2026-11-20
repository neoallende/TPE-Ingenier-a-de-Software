import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from trotamundos_reco import auth
from trotamundos_reco.config import Settings
from trotamundos_reco.db import Database, SqlStore
from trotamundos_reco.domain import (Accommodation, Constraints, FeatureSpace, Profile, Weights,
                                     apply_feedback, cosine, feedback_signal, ndcg_at_k,
                                     precision_at_k)
from trotamundos_reco.seed import build_catalog, seed_catalog
from trotamundos_reco.service import RecommenderService

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.settings = Settings(db_path=os.path.join(self._dir.name, "t.db"), jwt_secret="s3cret",
                                 ttl_seconds=600, top_k=10, max_retries=2)
        self.store = SqlStore(Database(self.settings.db_path))
        seed_catalog(self.store)
        self.clock = Clock()
        self.svc = RecommenderService(self.store, self.settings, clock=self.clock, sleep=lambda s: None)
        self.catalog = self.store.catalog()
        self.space = FeatureSpace.fit(self.catalog, Weights())

    def tearDown(self):
        self._dir.cleanup()

    def book(self, user, ids):
        for n, i in enumerate(ids):
            self.store.upsert_reservation(f"{user}-{n}", user, i, "confirmed")


class TestCatalogAndVectors(Base):
    def test_seed_is_40_and_deterministic(self):
        self.assertEqual(len(self.catalog), 40)
        self.assertEqual(build_catalog(), build_catalog())

    def test_cosine(self):
        self.assertAlmostEqual(cosine([1, 2], [2, 4]), 1.0)
        self.assertEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)

    def test_vector_normalised_and_sized(self):
        for a in self.catalog:
            v = self.space.encode(a)
            self.assertEqual(len(v), self.space.dim)
            self.assertTrue(0.0 <= v[0] <= 1.0 and 0.0 <= v[1] <= 1.0)

    def test_weights_parse(self):
        self.assertEqual(Weights.parse("stars=2,price=0.5").stars, 2.0)
        with self.assertRaises(ValueError):
            Weights.parse("foo=1")


class TestProfileAndFeedback(Base):
    def test_profile_inferred_as_mean_of_history(self):
        self.book("u", [1, 2, 3])
        p = self.svc._load_profile("u", self.catalog, self.space)
        expected = [sum(c) / 3 for c in zip(*[self.space.encode(self.catalog[i - 1]) for i in (1, 2, 3)])]
        self.assertEqual(p.interactions, 3)
        for x, y in zip(p.vector, expected):
            self.assertAlmostEqual(x, y)

    def test_signal_mapping(self):
        self.assertEqual(feedback_signal("accept"), 1.0)
        self.assertEqual(feedback_signal("reject"), -1.0)
        self.assertEqual([feedback_signal("rating", r) for r in (1, 3, 5)], [-1.0, 0.0, 1.0])
        with self.assertRaises(ValueError):
            feedback_signal("rating", 6)

    def test_accept_moves_closer_and_reject_moves_away(self):
        item = self.space.encode(self.catalog[33])
        base = Profile(self.space.encode(self.catalog[0]), 3, "history")
        closer = apply_feedback(base, item, 1.0, 0.3)
        away = apply_feedback(base, item, -1.0, 0.3)
        self.assertGreater(cosine(closer.vector, item), cosine(base.vector, item))
        self.assertLess(cosine(away.vector, item), cosine(base.vector, item))
        self.assertEqual(closer.interactions, 4)

    def test_feedback_is_idempotent(self):
        self.book("u", [1, 2])
        r1 = self.svc.submit_feedback("u", "fb-1", 34, "accept")
        p1 = self.store.get_profile("u")
        r2 = self.svc.submit_feedback("u", "fb-1", 34, "accept")
        self.assertTrue(r1["applied"])
        self.assertFalse(r2["applied"])
        self.assertEqual(self.store.get_profile("u"), p1)
        self.assertEqual(len(self.store.latest_signals("u")), 1)

    def test_feedback_validation(self):
        with self.assertRaises(LookupError):
            self.svc.submit_feedback("u", "x", 999, "accept")
        with self.assertRaises(ValueError):
            self.svc.submit_feedback("u", "", 1, "accept")
        with self.assertRaises(ValueError):
            self.svc.submit_feedback("u", "x", 1, "rating")

    def test_rejected_item_is_excluded(self):
        self.book("u", [34, 29])
        self.svc.generate_for_user("u")
        top = self.svc.get_recommendations("u")["items"][0]["accommodation_id"]
        self.svc.submit_feedback("u", "fb", top, "reject")
        self.svc.generate_for_user("u")
        ids = [i["accommodation_id"] for i in self.svc.get_recommendations("u")["items"]]
        self.assertNotIn(top, ids)


class TestRecommendations(Base):
    def test_personalized_prefers_similar_items(self):
        luxury = [a for a in self.catalog if a.stars >= 4][:4]
        self.book("lux", [a.id for a in luxury])
        self.svc.generate_for_user("lux")
        view = self.svc.get_recommendations("lux")
        self.assertEqual(view["strategy"], "personalized")
        self.assertEqual(len(view["items"]), 10)
        avg = sum(i["stars"] for i in view["items"][:5]) / 5
        self.assertGreaterEqual(avg, 3.5)

    def test_cold_start_when_few_data(self):
        self.book("one", [1])  # 1 < min_profile_interactions (2)
        self.svc.generate_for_user("one")
        self.svc.generate_for_user("ghost")
        self.assertEqual(self.svc.get_recommendations("one")["strategy"], "cold_start")
        self.assertEqual(self.svc.get_recommendations("ghost")["strategy"], "cold_start")
        self.assertEqual(len(self.svc.get_recommendations("ghost")["items"]), 10)

    def test_mandatory_constraints_never_violated(self):
        self.book("u", [34, 29, 24])
        self.svc.set_constraints("u", {"max_price_per_night": 120, "min_stars": 3,
                                       "required_amenities": ["wifi"]})
        self.svc.generate_for_user("u")
        items = self.svc.get_recommendations("u")["items"]
        by_id = {a.id: a for a in self.catalog}
        self.assertTrue(items)
        for i in items:
            a = by_id[i["accommodation_id"]]
            self.assertTrue(a.price_per_night <= 120 and a.stars >= 3 and "wifi" in a.amenities)

    def test_zero_candidates_yields_empty_with_reason(self):
        self.svc.set_constraints("u", {"max_price_per_night": 1})
        self.svc.generate_for_user("u")
        view = self.svc.get_recommendations("u")
        self.assertEqual((view["items"], view["reason"], view["status"]), ([], "no_candidates", "fresh"))

    def test_constraints_validation(self):
        with self.assertRaises(ValueError):
            self.svc.set_constraints("u", {"zones": ["marte"]})
        with self.assertRaises(ValueError):
            self.svc.set_constraints("u", {"min_stars": 9})

    def test_ttl_expires_to_empty_list(self):
        self.book("u", [1, 2])
        self.svc.generate_for_user("u")
        self.clock.advance(599)
        self.assertEqual(self.svc.get_recommendations("u")["status"], "fresh")
        self.clock.advance(1)
        view = self.svc.get_recommendations("u")
        self.assertEqual((view["status"], view["items"]), ("expired", []))

    def test_no_recommendations_before_first_cycle(self):
        self.assertEqual(self.svc.get_recommendations("new")["status"], "none")

    def test_users_are_isolated(self):
        self.book("a", [34, 29])
        self.book("b", [1, 6])
        self.svc.run_cycle()
        b_before = self.svc.get_recommendations("b")
        self.store.latest_signals("b")
        self.svc.submit_feedback("a", "fb", 40, "accept")
        self.svc.run_cycle()
        self.assertEqual(self.svc.get_recommendations("b")["items"], b_before["items"])
        self.assertEqual(self.store.latest_signals("b"), {})
        self.assertNotEqual(self.svc.get_recommendations("a")["items"], b_before["items"])


class TestFailureHandling(Base):
    def test_last_valid_set_kept_when_generation_fails(self):
        self.book("u", [1, 2])
        self.svc.run_cycle()
        before = self.svc.get_recommendations("u")["items"]
        self.clock.advance(60)
        original = self.store.catalog

        def boom():
            raise RuntimeError("catálogo caído")
        self.store.catalog = boom
        report = self.svc.run_cycle()
        self.store.catalog = original
        self.assertIn("u", report.failed)
        after = self.svc.get_recommendations("u")
        self.assertEqual(after["status"], "fresh")
        self.assertEqual(after["items"], before)

    def test_retry_recovers_without_duplicating_state(self):
        self.book("u", [1, 2])
        original, calls = self.store.catalog, {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transitorio")
            return original()
        self.store.catalog = flaky
        report = self.svc.run_cycle()
        self.assertEqual(report.ok, ["u"])
        with self.store.db.read() as c:
            n = c.execute("SELECT COUNT(*) FROM recommendation_sets").fetchone()[0]
        self.assertEqual(n, 1)


class TestAuthAndAudit(Base):
    def test_token_roundtrip_and_failures(self):
        tok = auth.issue_token("u1", "user", "s3cret", 60, T0)
        self.assertEqual(auth.verify_token(tok, "s3cret", T0), auth.Principal("u1", "user"))
        with self.assertRaises(auth.AuthError):
            auth.verify_token(tok, "otro", T0)
        with self.assertRaises(auth.AuthError):
            auth.verify_token(tok, "s3cret", T0 + timedelta(seconds=61))
        head, payload, sig = tok.split(".")
        forged = auth.issue_token("u1", "admin", "otro", 60, T0)
        with self.assertRaises(auth.AuthError):
            auth.verify_token(forged, "s3cret", T0)
        with self.assertRaises(auth.AuthError):
            auth.verify_token(f"{head}.{payload}.AAAA", "s3cret", T0)
        with self.assertRaises(auth.AuthError):
            auth.verify_token("basura", "s3cret", T0)

    def test_alg_none_rejected(self):
        h = auth._b64e(b'{"alg":"none","typ":"JWT"}')
        p = auth._b64e(b'{"sub":"u","role":"admin","exp":9999999999}')
        with self.assertRaises(auth.AuthError):
            auth.verify_token(f"{h}.{p}.", "s3cret", T0)

    def test_admin_access_is_audited_and_user_denied(self):
        self.book("u", [1, 2])
        with self.assertRaises(PermissionError):
            self.svc.admin_view_profile(auth.Principal("u", "user"), "u")
        self.assertEqual(self.store.list_audit(), [])
        view = self.svc.admin_view_profile(auth.Principal("root", "admin"), "u")
        self.assertEqual(view["user_id"], "u")
        log = self.svc.admin_audit_log(auth.Principal("root", "admin"))
        self.assertEqual([(e["admin_sub"], e["target_user_id"], e["action"]) for e in log],
                         [("root", "u", "view_profile")])
        with self.assertRaises(PermissionError):
            self.svc.admin_audit_log(auth.Principal("u", "user"))


class TestMetrics(unittest.TestCase):
    def test_precision_and_ndcg(self):
        self.assertAlmostEqual(precision_at_k([1, 2, 3, 4], {1, 3}, 4), 0.5)
        self.assertAlmostEqual(ndcg_at_k([1, 2], {1: 1.0}, 2), 1.0)
        self.assertLess(ndcg_at_k([2, 1], {1: 1.0}, 2), 1.0)
        self.assertEqual(ndcg_at_k([5], {}, 3), 0.0)

    def test_evaluate_user(self):
        base = Base("setUp")
        base.setUp()
        try:
            base.book("u", [34, 29])
            base.svc.generate_for_user("u")
            top = base.svc.get_recommendations("u")["items"][0]["accommodation_id"]
            base.svc.submit_feedback("u", "fb", top, "accept")
            ev = base.svc.evaluate_user("u", k=5)
            self.assertGreater(ev["precision_at_k"], 0)
        finally:
            base.tearDown()


if __name__ == "__main__":
    unittest.main()
