from __future__ import annotations

import unittest

from blackpod_build_week.modeldock_config import (
    MODELDOCK_BASE_URL_ENV,
    MODELDOCK_DELIVERY_GRACE_SECONDS_ENV,
    MODELDOCK_MODEL_ENV,
    MODELDOCK_PROFILE_ENV,
    MODELDOCK_PROVIDER_ENV,
    MODELDOCK_TIMEOUT_SECONDS_ENV,
    ModelDockConfig,
    ModelDockConfigurationError,
    load_modeldock_config,
)


class ModelDockConfigurationTests(unittest.TestCase):
    def valid_environment(self) -> dict[str, str]:
        return {
            MODELDOCK_BASE_URL_ENV: "http://127.0.0.1:8000/",
            MODELDOCK_TIMEOUT_SECONDS_ENV: "12.5",
        }

    def test_required_environment_and_safe_defaults(self) -> None:
        config = load_modeldock_config(environ=self.valid_environment())
        self.assertEqual(config.base_url, "http://127.0.0.1:8000")
        self.assertEqual(config.timeout_seconds, 12.5)
        self.assertEqual(config.profile, "default")
        self.assertEqual(config.provider, "mlx")
        self.assertIsNone(config.model)
        self.assertEqual(config.max_response_bytes, 1024 * 1024)
        self.assertEqual(config.delivery_grace_seconds, 30.0)
        self.assertEqual(config.delivery_timeout_seconds, 43.0)

    def test_missing_base_url_or_timeout_is_rejected(self) -> None:
        with self.assertRaisesRegex(ModelDockConfigurationError, "BASE_URL"):
            load_modeldock_config(environ={})
        with self.assertRaisesRegex(ModelDockConfigurationError, "TIMEOUT"):
            load_modeldock_config(
                environ={MODELDOCK_BASE_URL_ENV: "http://localhost:8000"}
            )

    def test_invalid_or_nonlocal_urls_are_rejected(self) -> None:
        for url in (
            "https://modeldock.example:8000",
            "ftp://127.0.0.1:8000",
            "http://user:secret@127.0.0.1:8000",
            "http://127.0.0.1:8000/api",
            "http://127.0.0.1:8000?token=secret",
            "http://127.0.0.1:8000#fragment",
        ):
            environment = self.valid_environment()
            environment[MODELDOCK_BASE_URL_ENV] = url
            with self.subTest(url=url), self.assertRaises(ModelDockConfigurationError):
                load_modeldock_config(environ=environment)

    def test_loopback_ipv6_and_localhost_are_accepted(self) -> None:
        for url in ("http://localhost:8000", "https://[::1]:8443"):
            environment = self.valid_environment()
            environment[MODELDOCK_BASE_URL_ENV] = url
            with self.subTest(url=url):
                self.assertEqual(load_modeldock_config(environ=environment).base_url, url)

    def test_timeout_must_be_finite_positive_and_bounded(self) -> None:
        for value in ("", "zero", "0", "-1", "nan", "inf", "1801"):
            environment = self.valid_environment()
            environment[MODELDOCK_TIMEOUT_SECONDS_ENV] = value
            with self.subTest(value=value), self.assertRaises(ModelDockConfigurationError):
                load_modeldock_config(environ=environment)

    def test_explicit_long_service_budget_is_bounded_without_changing_default(self) -> None:
        for value in ("300", "301", "1800"):
            environment = self.valid_environment()
            environment[MODELDOCK_TIMEOUT_SECONDS_ENV] = value
            with self.subTest(value=value):
                config = load_modeldock_config(environ=environment)
                self.assertEqual(config.timeout_seconds, float(value))
                self.assertEqual(config.delivery_timeout_seconds, float(value) + 30)
        self.assertEqual(
            load_modeldock_config(environ=self.valid_environment()).timeout_seconds,
            12.5,
        )

    def test_delivery_grace_environment_is_optional_finite_and_bounded(self) -> None:
        for value in ("", "zero", "-1", "nan", "inf", "-inf", "120.1", "true"):
            environment = self.valid_environment()
            environment[MODELDOCK_DELIVERY_GRACE_SECONDS_ENV] = value
            with self.subTest(value=value), self.assertRaisesRegex(
                ModelDockConfigurationError, "DELIVERY_GRACE"
            ):
                load_modeldock_config(environ=environment)

    def test_explicit_delivery_grace_and_zero_are_supported(self) -> None:
        for value in ("0", "0.5", "120"):
            environment = self.valid_environment()
            environment[MODELDOCK_DELIVERY_GRACE_SECONDS_ENV] = value
            with self.subTest(value=value):
                config = load_modeldock_config(environ=environment)
                self.assertEqual(config.delivery_grace_seconds, float(value))
                self.assertEqual(config.delivery_timeout_seconds, 13 + float(value))

    def test_direct_budget_and_grace_must_be_finite_numbers_not_bools(self) -> None:
        for field, values in (
            ("timeout_seconds", (True, False, "30", None, float("inf"), -1, 1801)),
            (
                "delivery_grace_seconds",
                (True, False, "30", None, float("nan"), float("inf"), -1, 120.1),
            ),
        ):
            for value in values:
                kwargs = {"timeout_seconds": 10.0, field: value}
                with self.subTest(field=field, value=value), self.assertRaises(
                    ModelDockConfigurationError
                ):
                    ModelDockConfig("http://localhost:8000", **kwargs)

    def test_direct_grace_total_uses_ceil_service_budget_and_preserves_positions(self) -> None:
        config = ModelDockConfig(
            "http://localhost:8000", 12.5, "default", "legacy", "mlx", 4096
        )
        self.assertEqual(config.model, "legacy")
        self.assertEqual(config.max_response_bytes, 4096)
        self.assertEqual(config.delivery_grace_seconds, 30.0)
        self.assertEqual(config.delivery_timeout_seconds, 43.0)
        for budget, grace, total in ((0.1, 0, 1), (12.5, 0.5, 13.5), (1800, 120, 1920)):
            with self.subTest(budget=budget, grace=grace):
                config = ModelDockConfig(
                    "http://localhost:8000", budget, delivery_grace_seconds=grace
                )
                self.assertEqual(config.delivery_timeout_seconds, total)
                self.assertIsInstance(config.delivery_grace_seconds, float)

    def test_optional_profile_and_mlx_policy_leave_model_selection_to_appliance(self) -> None:
        environment = self.valid_environment()
        environment.update(
            {
                MODELDOCK_PROFILE_ENV: "oracle-narrative",
                MODELDOCK_MODEL_ENV: "mlx-community/test-model",
                MODELDOCK_PROVIDER_ENV: "mlx",
            }
        )
        config = load_modeldock_config(environ=environment)
        self.assertEqual(config.profile, "oracle-narrative")
        self.assertIsNone(config.model)

        environment[MODELDOCK_PROVIDER_ENV] = "ollama"
        with self.assertRaisesRegex(ModelDockConfigurationError, "mlx"):
            load_modeldock_config(environ=environment)

    def test_legacy_model_environment_is_ignored_not_propagated(self) -> None:
        for value in ("old-model", "/Users/demo/model", "sk-proj-private-value", ""):
            environment = self.valid_environment()
            environment[MODELDOCK_MODEL_ENV] = value
            with self.subTest(value=value):
                config = load_modeldock_config(environ=environment)
                self.assertIsNone(config.model)
                if value:
                    self.assertNotIn(value, repr(config))

    def test_direct_construction_enforces_every_safety_invariant(self) -> None:
        valid = {
            "base_url": "http://127.0.0.1:8000",
            "timeout_seconds": 10.0,
        }
        mutations = (
            {"base_url": "https://modeldock.example"},
            {"base_url": "file:///tmp/modeldock.sock"},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": 0},
            {"timeout_seconds": 1801},
            {"provider": "ollama"},
            {"provider": "MLX"},
            {"profile": "/private/profile"},
            {"model": "file://private/model"},
            {"model": "sk-proj-abcdefghijk"},
            {"max_response_bytes": 0},
            {"max_response_bytes": 1024 * 1024 + 1},
            {"max_response_bytes": 1.5},
        )
        for mutation in mutations:
            values = {**valid, **mutation}
            with self.subTest(mutation=mutation), self.assertRaises(
                ModelDockConfigurationError
            ):
                ModelDockConfig(**values)

        normalized = ModelDockConfig(
            base_url="http://localhost:8000/",
            timeout_seconds=1,
            max_response_bytes=4096,
        )
        self.assertEqual(normalized.base_url, "http://localhost:8000")
        self.assertEqual(normalized.timeout_seconds, 1.0)


if __name__ == "__main__":
    unittest.main()
