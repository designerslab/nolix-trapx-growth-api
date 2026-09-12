# Keyword Quality Patch v13.1

Add:
- app/growth_agent/keyword_quality.py
- tests/test_keyword_quality.py

Apply:
- patch_instructions.txt

Run:
python -m pytest -q

Fixes:
- URL query-string duplicates
- duplicate query/page variants
- branded new keywords
- low-value support/navigation queries
- clearly off-topic TrapX queries
