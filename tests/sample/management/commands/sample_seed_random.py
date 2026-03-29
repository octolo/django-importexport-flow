"""
Create random Author and Book rows for local demos and tests.

Usage::

    DJANGO_SETTINGS_MODULE=tests.settings python manage.py sample_seed_random
    DJANGO_SETTINGS_MODULE=tests.settings python manage.py sample_seed_random --authors 20 --books 50 --seed 42
"""

from __future__ import annotations

import random
from decimal import Decimal

from django.core.management.base import BaseCommand

from tests.sample.models import Author, Book

_FIRST = (
    "Ada",
    "Alan",
    "Grace",
    "James",
    "Katherine",
    "Linus",
    "Margaret",
    "Tim",
    "Ursula",
    "Yukihiro",
)
_LAST = (
    "Brown",
    "Chen",
    "Davis",
    "Garcia",
    "Harris",
    "Johnson",
    "Kim",
    "Martin",
    "Nguyen",
    "Petrov",
)
_ADJECTIVES = (
    "Ancient",
    "Blue",
    "Cosmic",
    "Distant",
    "Emerald",
    "Forgotten",
    "Golden",
    "Hidden",
    "Ivory",
    "Jade",
)
_NOUNS = (
    "Algorithm",
    "Bridge",
    "Compass",
    "Dragon",
    "Echo",
    "Forest",
    "Garden",
    "Harbor",
    "Island",
    "Journey",
)


class Command(BaseCommand):
    help = "Insert random Author and Book rows (sample app)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--authors",
            type=int,
            default=12,
            help="Number of authors to create (default: 12).",
        )
        parser.add_argument(
            "--books",
            type=int,
            default=40,
            help="Total number of books to create (default: 40).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Optional RNG seed for reproducible output.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing Author rows (cascades to their Books) before seeding.",
        )

    def handle(self, *args, **options):
        authors_n: int = options["authors"]
        books_n: int = options["books"]
        seed = options["seed"]
        if seed is not None:
            random.seed(seed)

        if options["clear"]:
            deleted_a, _ = Author.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted_a} author(s) (and related books)."))

        authors = []
        for _ in range(authors_n):
            name = f"{random.choice(_FIRST)} {random.choice(_LAST)}"
            if Author.objects.filter(name=name).exists():
                name = f"{name} ({random.randint(1000, 9999)})"
            authors.append(Author.objects.create(name=name))

        created_books = 0
        for _ in range(books_n):
            title = f"{random.choice(_ADJECTIVES)} {random.choice(_NOUNS)}"
            if Book.objects.filter(title=title).exists():
                title = f"{title} #{random.randint(1, 9999)}"
            pages = random.randint(1, 900)
            price = Decimal(str(round(random.uniform(4.99, 89.99), 2)))
            meta = {
                "lang": random.choice(["en", "fr", "de", "es"]),
                "edition": random.randint(1, 5),
            }
            author = None
            if authors and random.random() > 0.12:
                author = random.choice(authors)
            Book.objects.create(
                title=title[:100],
                pages=pages,
                price=price,
                metadata=meta,
                author=author,
            )
            created_books += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(authors)} author(s) and {created_books} book(s)."
            )
        )
