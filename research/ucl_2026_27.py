"""2026/27 UEFA Champions League projection, as of 13 October 2026.

Official fixed 144 fixtures, 18 known results. Prospective scenario research,
NOT verified live forecasts nor exact five-league XGQ on out-of-league clubs.
Uses UEFA draw-pot tier prior (explicit modeling assumption) and locally saved
private Understat team xG, XGQ, shots only for supported five-league teams.
No private Understat rows leave this module; publish model-derived aggregates.
"""
from __future__ import annotations
import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
