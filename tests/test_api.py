import unittest
from api import list_items

class InventoryTests(unittest.TestCase):
    def test_items_have_unique_ids(self):
        items = list_items()
        self.assertEqual(len(items), len({i["id"] for i in items}))
        self.assertTrue(all(i["quantity"] >= 0 for i in items))
    def test_items_are_fresh_values(self):
        items = list_items(); items[0]["quantity"] = -1
        self.assertGreaterEqual(list_items()[0]["quantity"], 0)
