from app.growth_agent.keyword_quality import canonical_page, filter_keyword_rows

def test_canonical_page_removes_query_string():
    assert canonical_page("https://trapx.io/products/a?x=1#test") == "https://trapx.io/products/a"

def test_dedupes_tracking_variant():
    rows = [
        {"query":"mouse trap mechanism","page":"https://trapx.io/blogs/news/a","impressions":3,"position":12},
        {"query":"mouse trap mechanism","page":"https://trapx.io/blogs/news/a?cvv=123","impressions":3,"position":12},
    ]
    assert len(filter_keyword_rows("trapx", rows)) == 1

def test_filters_off_topic_trapx_query():
    rows = [{"query":"project zomboid mouse trap how to use","page":"https://trapx.io/blogs/news/zomboid","impressions":4,"position":8.7}]
    assert filter_keyword_rows("trapx", rows) == []

def test_keeps_relevant_trapx_query():
    rows = [{"query":"rodent detector kit","page":"https://trapx.io/","impressions":2,"position":1}]
    assert len(filter_keyword_rows("trapx", rows)) == 1

def test_keeps_relevant_nolix_query():
    rows = [{"query":"water damage moisture readings","page":"https://nolix.ai/blogs/news/water-damage-moisture-meter-guide","impressions":13,"position":89.5}]
    assert len(filter_keyword_rows("nolix", rows)) == 1
