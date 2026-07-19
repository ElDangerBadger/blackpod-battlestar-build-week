from __future__ import annotations

import unittest

from blackpod_build_week.modeldock_config import (
    MODELDOCK_BASE_URL_ENV,
    MODELDOCK_MODEL_ENV,
    MODELDOCK_PROFILE_ENV,
    MODELDOCK_PROVIDER_ENV,
    MODELDOCK_TIMEOUT_SECONDS_ENV,
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
        for value in ("", "zero", "0", "-1", "nan", "inf", "301"):
            environment = self.valid_environment()
            environment[MODELDOCK_TIMEOUT_SECONDS_ENV] = value
            with self.subTest(value=value), self.assertRaises(ModelDockConfigurationError):
                load_modeldock_config(environ=environment)

    def test_optional_selection_and_mlx_policy(self) -> None:
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
        self.assertEqual(config.model, "mlx-community/test-model")

        environment[MODELDOCK_PROVIDER_ENV] = "ollama"
        with self.assertRaisesRegex(ModelDockConfigurationError, "mlx"):
            load_modeldock_config(environ=environment)

    def test_model_may_not_be_an_absolute_path(self) -> None:
        environment = self.valid_environment()
        environment[MODELDOCK_MODEL_ENV] = "/Users/demo/model"
        with self.assertRaises(ModelDockConfigurationError):
            load_modeldock_config(environ=environment)

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
            {"timeout_seconds": 301},
            {"provider": "ollama"},
            {"provider": "MLX"},
            {"profile": "/private/profile"},
            {"model": "file://private/model"},
            {"model": "sk-proj-abcdefghijk"},
            {"max_response_bytes": 0},
            {"max_response_bytes": 1024 * 1024 + 1},
            {"max_response_bytes": 1.5},
        )
        from blackpod_build_week.modeldock_config import ModelDockConfig

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
