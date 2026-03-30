"""
Unit tests for DocumentTaxonomyClassifier
"""


from src.core.ingestion.application.document_taxonomy import classify_document_taxonomy

# ---------------------------------------------------------------------------
# Folder-based rules
# ---------------------------------------------------------------------------

def test_admin_guide_maps_to_commercial_admin():
    result = classify_document_taxonomy(folder_name="AdminGuide")
    assert result["edition"] == "commercial"
    assert result["audience"] == "admin"
    assert result["source_family"] == "admin_guide"
    assert result["product_line"] == "carbonio"


def test_ce_guide_maps_to_ce_admin():
    result = classify_document_taxonomy(folder_name="CEGuide")
    assert result["edition"] == "ce"
    assert result["audience"] == "admin"
    assert result["source_family"] == "ce_guide"
    assert result["product_line"] == "carbonio"


def test_user_guide_maps_to_commercial_user():
    result = classify_document_taxonomy(folder_name="UserGuide")
    assert result["edition"] == "commercial"
    assert result["audience"] == "user"
    assert result["source_family"] == "user_guide"
    assert result["product_line"] == "carbonio"


def test_unknown_folder_yields_unknown():
    result = classify_document_taxonomy(folder_name="RandomFolder")
    assert result["edition"] == "unknown"
    assert result["audience"] == "unknown"
    assert result["source_family"] == "unknown"


def test_no_folder_yields_unknown():
    result = classify_document_taxonomy(folder_name=None)
    assert result["edition"] == "unknown"
    assert result["audience"] == "unknown"
    assert result["source_family"] == "unknown"


# ---------------------------------------------------------------------------
# ZendeskKB heuristics
# ---------------------------------------------------------------------------

def test_zendesk_kb_with_admin_title():
    result = classify_document_taxonomy(
        folder_name="ZendeskKB", document_title="How to install Carbonio on Ubuntu"
    )
    assert result["edition"] == "commercial"
    assert result["audience"] == "admin"
    assert result["source_family"] == "zendesk_kb"


def test_zendesk_kb_with_user_title():
    result = classify_document_taxonomy(
        folder_name="ZendeskKB", document_title="How to use webmail and send email"
    )
    assert result["edition"] == "commercial"
    assert result["audience"] == "user"
    assert result["source_family"] == "zendesk_kb"


def test_zendesk_kb_admin_keyword_domain():
    result = classify_document_taxonomy(
        folder_name="ZendeskKB", document_title="Configuring domain settings"
    )
    assert result["audience"] == "admin"


def test_zendesk_kb_user_keyword_calendar():
    result = classify_document_taxonomy(
        folder_name="ZendeskKB", document_title="Managing your calendar appointments"
    )
    assert result["audience"] == "user"


def test_zendesk_kb_no_title_yields_unknown_audience():
    result = classify_document_taxonomy(folder_name="ZendeskKB", document_title=None)
    assert result["edition"] == "commercial"
    assert result["audience"] == "unknown"
    assert result["source_family"] == "zendesk_kb"


def test_zendesk_kb_ambiguous_title_yields_unknown_audience():
    result = classify_document_taxonomy(
        folder_name="ZendeskKB", document_title="General information about Carbonio"
    )
    assert result["audience"] == "unknown"


def test_zendesk_kb_admin_keyword_wins_when_both_present():
    # If both admin and user keywords appear, admin wins (conservative default)
    result = classify_document_taxonomy(
        folder_name="ZendeskKB",
        document_title="Admin backup configuration using webmail",
    )
    assert result["audience"] == "admin"


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

def test_result_always_has_all_keys():
    result = classify_document_taxonomy(folder_name=None)
    assert set(result.keys()) == {"product_line", "edition", "audience", "source_family"}


def test_folder_name_is_case_insensitive():
    result = classify_document_taxonomy(folder_name="adminguide")
    assert result["edition"] == "commercial"
    assert result["audience"] == "admin"
