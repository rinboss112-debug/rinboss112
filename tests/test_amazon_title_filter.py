from __future__ import annotations

import unittest

from amazon_scraper import _title_contains_amazon


class AmazonTitleFilterTests(unittest.TestCase):
    def test_rejects_amazon_in_any_common_form(self) -> None:
        rejected = (
            "Amazon Basics Storage Box",
            "amazon.com Gift Card",
            "AMAZON Fire TV Stick",
            "AmazonBasics Cable",
        )
        for title in rejected:
            with self.subTest(title=title):
                self.assertTrue(_title_contains_amazon(title))

    def test_keeps_titles_without_amazon(self) -> None:
        accepted = (
            "Healthy Snack Variety Pack",
            "Kitchen Drawer Organizer",
            "Pet Grooming Brush",
        )
        for title in accepted:
            with self.subTest(title=title):
                self.assertFalse(_title_contains_amazon(title))


if __name__ == "__main__":
    unittest.main()
