import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routed_presets import ROUTED_PRESETS, get_routed_preset_map, get_routed_preset_name


class TestRoutedPresets(unittest.TestCase):
    def test_all_known_presets_resolve_by_name(self):
        for name, values, _desc in ROUTED_PRESETS:
            self.assertEqual(
                get_routed_preset_name(
                    values["routed_cache_enabled"],
                    values["routed_cache_ttl"],
                    values["routed_reply_ttl"],
                    optimistic_cache_enabled=values.get("optimistic_cache_enabled"),
                    stale_cache_ttl=values.get("stale_cache_ttl"),
                ),
                name,
            )

    def test_unknown_values_return_custom(self):
        # Произвольные значения, не совпадающие ни с одним пресетом
        self.assertEqual(
            get_routed_preset_name(
                True, 9, 2,
                optimistic_cache_enabled=True,
                stale_cache_ttl=3600,
            ),
            "Пользовательский",
        )

    def test_optimistic_fields_differentiate_presets(self):
        # «Рекомендуемый» при выключенном optimistic должен превратиться
        # в «Пользовательский» — иначе тогл бы ни на что не влиял.
        rec = dict(ROUTED_PRESETS[1][1])
        self.assertEqual(
            get_routed_preset_name(
                rec["routed_cache_enabled"],
                rec["routed_cache_ttl"],
                rec["routed_reply_ttl"],
                optimistic_cache_enabled=False,
                stale_cache_ttl=rec["stale_cache_ttl"],
            ),
            "Пользовательский",
        )

    def test_get_routed_preset_map_contains_expected_keys(self):
        preset_map = get_routed_preset_map()
        self.assertIn("Совместимый", preset_map)
        self.assertIn("Рекомендуемый", preset_map)
        self.assertIn("Скоростной", preset_map)


if __name__ == "__main__":
    unittest.main()
