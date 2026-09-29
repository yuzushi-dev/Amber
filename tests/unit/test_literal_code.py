import asyncio

import pytest

from src.core.generation.application.generation_service import GenerationService
from src.core.generation.application.literal_code import (
    AMBIGUOUS_CODE_MARKER,
    OMISSION_MARKER,
    guard_literal_code,
)


@pytest.mark.parametrize(
    ("answer", "source", "expected"),
    [
        ("`ready`", {1: "ready"}, "`ready`"),
        ("```python\nprint(1)\n```", {1: "print(1)"}, "```python\nprint(1)\n```"),
        ("```js\rcode\r```", {1: "code"}, "```js\rcode\r```"),
        ("```js\rcode\r```\r", {1: "code"}, "```js\rcode\r```\r"),
        ("```js\r\ncode\r\n```\r\n", {1: "code"}, "```js\r\ncode\r\n```\r\n"),
        ("````python\nprint('```')\n````", {1: "print('```')"}, "````python\nprint('```')\n````"),
        ("``m(`label.view_mail`, `VIEW MAIL`)``", {1: "m(`label.view_mail`, `VIEW MAIL`)"}, "``m(`label.view_mail`, `VIEW MAIL`)``"),
        ("```js\nm(`label.view_mail`, `VIEW MAIL`)\n```", {1: "m(`label.view_mail`, `VIEW MAIL`)"}, "```js\nm(`label.view_mail`, `VIEW MAIL`)\n```"),
        ("raw `literal`", {1: "raw `literal`"}, "raw `literal`"),
    ],
)
def test_verbatim_and_unambiguous_wrappers_are_preserved(answer, source, expected):
    assert guard_literal_code(answer, source) == expected


@pytest.mark.parametrize(
    "answer",
    [
        "`select A`",  # case differs
        "<pre><code>run()</code></pre>",
        "    run()\n",
        "```outer\n```inner\nvalue\n```\n```",
    ],
)
def test_nonmatching_or_ambiguous_code_is_omitted(answer):
    guarded = guard_literal_code(answer, {1: "call(`x`)\nSELECT  A\nrun()\nvalue"})
    assert OMISSION_MARKER in guarded
    assert answer not in guarded
    assert "Original source excerpts" in guarded
    assert "[[Source: 1]]" in guarded


def test_empty_and_truncation_ellipsis_are_not_source_matches():
    assert guard_literal_code("``", {1: "anything"}) == guard_literal_code("``", {})
    guarded = guard_literal_code("`prefix...`", {2: "prefix"})
    assert OMISSION_MARKER in guarded
    assert "[[Source: 2]]" in guarded


def test_wrapper_match_is_sensitive_and_fence_uses_safe_length():
    assert OMISSION_MARKER in guard_literal_code("`Code`", {1: "code"})
    source = "line with ```` inside"
    answer = "```python\nline with ```` inside\n```"
    guarded = guard_literal_code(answer, {7: source})
    assert guarded == answer


def test_ambiguous_three_span_wrapper_is_rejected_when_only_body_matches_source():
    answer = "`m(`label.view_mail`, `VIEW MAIL`)`"
    source = "m(`label.view_mail`, `VIEW MAIL`)"

    guarded = guard_literal_code(answer, {1: source})

    assert guarded.startswith(AMBIGUOUS_CODE_MARKER)
    assert answer not in guarded
    assert source in guarded


@pytest.mark.parametrize(
    "answer",
    [
        "`m(`label.view_mail`, `VIEW MAIL`)`",
        "`one` then `two` and `three`",
    ],
)
def test_ambiguous_inline_markup_is_preserved_when_raw_text_matches_source(answer):
    assert guard_literal_code(answer, {1: answer}) == answer


def test_separate_inline_spans_are_not_joined_without_verbatim_combined_body():
    answer = "Call `one` then `two` then `three`."

    assert guard_literal_code(answer, {1: "one two three"}) == answer


def test_multiple_ambiguous_groups_on_one_line_are_rejected_separately():
    answer = "Use `m(`label.a`, `A`)` then `n(`label.b`, `B`)`."
    sources = {
        1: "m(`label.a`, `A`)",
        2: "n(`label.b`, `B`)",
    }

    guarded = guard_literal_code(answer, sources)

    assert guarded.count(AMBIGUOUS_CODE_MARKER) == 2
    assert answer not in guarded
    assert all(source in guarded for source in sources.values())


def test_inline_ambiguity_scanner_does_not_inspect_fenced_source_text():
    answer = "```markdown\n`m(`label.view_mail`, `VIEW MAIL`)`\n```"

    assert guard_literal_code(answer, {1: answer}) == answer


def test_ambiguous_span_omission_preserves_crlf_after_line():
    answer = "`m(`label.view_mail`, `VIEW MAIL`)`\r\nNext line."
    guarded = guard_literal_code(
        answer, {1: "m(`label.view_mail`, `VIEW MAIL`)"}
    )

    assert guarded.startswith(AMBIGUOUS_CODE_MARKER + "\r\nNext line.")


@pytest.mark.parametrize(
    ("answer", "sources", "expected_prefix", "marker_count"),
    [
        (
            "`m(`label.view_mail`, `VIEW MAIL`)`",
            {1: "m(`label.view_mail`, `VIEW MAIL`)"},
            AMBIGUOUS_CODE_MARKER,
            1,
        ),
        (
            "Before `m(`label.view_mail`, `VIEW MAIL`)` after",
            {1: "m(`label.view_mail`, `VIEW MAIL`)"},
            f"Before {AMBIGUOUS_CODE_MARKER} after",
            1,
        ),
        (
            "`m(`label.view_mail`, `VIEW MAIL`)`\nNext",
            {1: "m(`label.view_mail`, `VIEW MAIL`)"},
            AMBIGUOUS_CODE_MARKER + "\nNext",
            1,
        ),
        (
            "`m(`label.view_mail`, `VIEW MAIL`)`\r\nNext",
            {1: "m(`label.view_mail`, `VIEW MAIL`)"},
            AMBIGUOUS_CODE_MARKER + "\r\nNext",
            1,
        ),
        (
            "`m(`label.view_mail`, `VIEW MAIL`)`\rNext",
            {1: "m(`label.view_mail`, `VIEW MAIL`)"},
            AMBIGUOUS_CODE_MARKER + "\rNext",
            1,
        ),
        (
            "First `m(`label.view_mail`, `VIEW MAIL`)` then `m(`label.view_mail`, `VIEW MAIL`)` end",
            {1: "m(`label.view_mail`, `VIEW MAIL`)"},
            f"First {AMBIGUOUS_CODE_MARKER} then {AMBIGUOUS_CODE_MARKER} end",
            2,
        ),
    ],
)
def test_ambiguous_omission_has_specific_marker_and_preserves_context(
    answer, sources, expected_prefix, marker_count,
):
    guarded = guard_literal_code(answer, sources)

    assert guarded.startswith(expected_prefix)
    assert guarded.count(AMBIGUOUS_CODE_MARKER) == marker_count
    assert OMISSION_MARKER not in guarded


def test_source_section_is_absent_when_no_excerpt_was_supplied():
    answer = guard_literal_code("`bad`", {})
    assert OMISSION_MARKER in answer
    assert "Original source excerpts" not in answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        "Prose paragraph.\n\n```py\nmutated()\n```\n\nEnd.",
        "Prose paragraph.\r\n\r\n```py\r\nmutated()\r\n```\r\nEnd.",
        "Prose paragraph.\n\ninline `mutated\ncode` end.",
        "Prose paragraph.\n\n- item\n    mutated()\n",
        "Prose paragraph.\n\n> ```\n> mutated()\n> ```",
        "Prose paragraph.\n\n```\nsafe source\n``` [[Source: 4]]\n\nEnd `mutated()`.",
    ],
)
async def test_streamed_guard_matches_sync_result_for_every_two_chunk_split(answer):
    expected = guard_literal_code(answer, {4: "safe source"})
    service = object.__new__(GenerationService)
    follow_up_answers = []
    service._generate_follow_ups = lambda query, text: follow_up_answers.append(text) or []

    class Provider:
        model_name = "test-model"
        provider_name = "test-provider"

        def __init__(self, parts):
            self.parts = parts

        async def generate_stream(self, **kwargs):
            for part in self.parts:
                yield part

    for split in range(1, len(answer)):
        prepared = type(
            "Prepared",
            (),
            {
                "provider": Provider([answer[:split], answer[split:]]),
                "user_prompt": "",
                "system_prompt": "",
                "temperature": 0,
                "max_tokens": 100,
                "seed": None,
                "model": "test-model",
                "stream_kwargs": {},
                "conversation_history": (),
                "source_excerpts": {4: "safe source"},
                "user_id": None,
                "api_key_id": None,
                "query": "question",
                "tenant_id": "tenant",
            },
        )()
        events = [event async for event in service.stream_prepared(prepared)]
        streamed = "".join(event["data"] for event in events if event["event"] == "token")
        done = next(event["data"] for event in events if event["event"] == "done")
        assert streamed == expected
        assert done["follow_ups"] == []
        assert follow_up_answers[-1] == expected


@pytest.mark.asyncio
async def test_stream_flushes_safe_paragraph_before_eof_and_does_not_flush_error_tail():
    service = object.__new__(GenerationService)
    service._generate_follow_ups = lambda query, text: []
    emitted = []

    class Provider:
        model_name = "test-model"
        provider_name = "test-provider"

        async def generate_stream(self, **kwargs):
            yield "Safe paragraph.\n\n"
            yield "```py\nmutated()\n```"
            raise RuntimeError("provider failed")

    prepared = type(
        "Prepared",
        (),
        {
            "provider": Provider(),
            "user_prompt": "",
            "system_prompt": "",
            "temperature": 0,
            "max_tokens": 100,
            "seed": None,
            "model": "test-model",
            "stream_kwargs": {},
            "conversation_history": (),
            "source_excerpts": {1: "safe"},
            "user_id": None,
            "api_key_id": None,
            "query": "question",
            "tenant_id": "tenant",
        },
    )()
    stream = service.stream_prepared(prepared)
    first = await anext(stream)
    assert first == {"event": "token", "data": "Safe paragraph.\n\n"}
    emitted.append(first["data"])
    with pytest.raises(RuntimeError, match="provider failed"):
        async for event in stream:
            if event["event"] == "token":
                emitted.append(event["data"])
    assert "".join(emitted) == "Safe paragraph.\n\n"


@pytest.mark.asyncio
async def test_stream_cancellation_does_not_flush_unverified_tail():
    service = object.__new__(GenerationService)
    provider_started = asyncio.Event()

    class Provider:
        model_name = "test-model"
        provider_name = "test-provider"

        async def generate_stream(self, **kwargs):
            yield "```py\nmutated()\n```"
            provider_started.set()
            await asyncio.Future()

    prepared = type(
        "Prepared",
        (),
        {
            "provider": Provider(),
            "user_prompt": "",
            "system_prompt": "",
            "temperature": 0,
            "max_tokens": 100,
            "seed": None,
            "model": "test-model",
            "stream_kwargs": {},
            "conversation_history": (),
            "source_excerpts": {1: "safe"},
            "user_id": None,
            "api_key_id": None,
            "query": "question",
            "tenant_id": "tenant",
        },
    )()
    stream = service.stream_prepared(prepared)
    next_event = asyncio.create_task(anext(stream))
    await provider_started.wait()
    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event


@pytest.mark.parametrize(
    ("answer", "source"),
    [
        # column-aligned command output in the source
        ("`wsc_basic enabled true`", {1: "wsc_basic        enabled      true"}),
        # inner whitespace run (was strict before 2026-09-26: cosmetic by decision)
        ("`SELECT A`", {1: "call(`x`)\nSELECT  A\nrun()\nvalue"}),
        # Markdown-escaped punctuation in the stored source text
        ("`Outl*`", {1: "search for Outl\\* to broaden results"}),
        # shell prompt and backslash continuation in the source
        (
            "```\nacmectl prov ms mail.example.com acmeMtaMyNetworks '127.0.0.0/8 10.0.0.0/24'\n```",
            {1: "acme$ acmectl prov ms mail.example.com \\\n    acmeMtaMyNetworks '127.0.0.0/8 10.0.0.0/24'"},
        ),
    ],
)
def test_formatting_only_differences_are_not_omitted(answer, source):
    assert guard_literal_code(answer, source) == answer


@pytest.mark.parametrize(
    ("answer", "source"),
    [
        # a changed value is still a different literal
        ("`ufw allow 20000:50000/udp`", {1: "ufw allow 20000:40000/udp"}),
        ("`acmectl prov ms host acmeMtaMyNetworks`", {1: "acme$ acmectl prov ms host \\\n acmeMtaTrustedNetworks"}),
        # leading indentation is meaningful (YAML nesting)
        ("```yaml\nservices:\napi:\n  image: x\n```", {1: "services:\n  api:\n    image: x"}),
    ],
)
def test_canonical_comparison_still_rejects_changed_literals(answer, source):
    assert guard_literal_code(answer, source).startswith(OMISSION_MARKER)


def test_split_spans_around_literal_backticks_stay_ambiguous_despite_spacing():
    # Markdown splits this around the literal `FALSE`; keeping the pieces would
    # render the code without its backticks. Source differs only in spacing.
    answer = "Use `!d && j?.attrs?.x == `FALSE` && (0, W.jsx)(X, {` here."
    source = {3: "``` !d &&    j?.attrs?.x == `FALSE` &&    (0, W.jsx)(X, { ```"}
    guarded = guard_literal_code(answer, source)
    assert AMBIGUOUS_CODE_MARKER in guarded
    assert "`!d && j?.attrs?.x == `" not in guarded.split("Original source excerpts")[0]


def test_nbsp_in_html_sourced_command_is_formatting_only():
    # HTML-derived sources separate tokens with NBSP; the model writes plain spaces.
    answer = "Run:\n\n```\nacmectl prov modifyConfig acmeReverseProxyMailMode both\n```\n"
    source = {5: "```\nacmectl prov modifyConfig\xa0acmeReverseProxyMailMode both\n```"}
    assert guard_literal_code(answer, source) == answer
    changed = answer.replace("both", "http")
    assert guard_literal_code(changed, source).startswith("Run:\n\n" + OMISSION_MARKER)


TABLE_CELL_SOURCE = {
    1: "| **Option 2** |\n"
    "| ```  !d &&     j?.attrs?.acmeIsAdminAccount == `TRUE` &&     (0, W.jsx)(X, { ``` |\n"
}


def test_code_squeezed_into_a_table_cell_matches_when_reflowed():
    answer = (
        "Insert:\n\n```js\n!d &&\n  j?.attrs?.acmeIsAdminAccount == `TRUE` &&\n"
        "  (0, W.jsx)(X, {\n```"
    )
    assert guard_literal_code(answer, TABLE_CELL_SOURCE) == answer


def test_table_cell_reflow_still_rejects_changed_literals_and_non_cell_sources():
    changed = "```js\n!d &&\n  j?.attrs?.acmeIsAdminAccount == `FALSE` &&\n```"
    assert OMISSION_MARKER in guard_literal_code(changed, TABLE_CELL_SOURCE)
    # Outside table cells line structure stays significant (YAML indentation).
    flattened = "```yaml\nroot: child: 1\n```"
    assert OMISSION_MARKER in guard_literal_code(flattened, {1: "root:\n  child: 1"})


def test_inline_span_echoing_a_query_term_is_kept():
    answer = "Search for `Outl*` to match Outlook."
    source = {1: "Place an asterisk (*) after a prefix to find similar words."}
    query = 'Will a search for "Outl" find "Outlook"?'
    assert guard_literal_code(answer, source, query) == answer
    assert OMISSION_MARKER in guard_literal_code(answer, source)
    assert OMISSION_MARKER in guard_literal_code("Search for `Outx*`.", source, query)
    multi_line = "```\nOutl*\n```"
    assert OMISSION_MARKER in guard_literal_code(multi_line, source, query)


def test_rewritten_command_placeholders_stay_omitted():
    source = {
        1: '```\nuser$ acmectl backup doRestoreOnNewAccount Account name or id '
        'destination_account "dd/MM/yyyy HH:mm:ss"|last\n```'
    }
    answer = (
        '```bash\nuser$ acmectl backup doRestoreOnNewAccount {source_account} '
        '{destination_account} "dd/MM/yyyy HH:mm:ss"|last\n```'
    )
    assert OMISSION_MARKER in guard_literal_code(answer, source, "restore on new account")


QUOTA_SCRIPT_SOURCE = {
    1: "```\ncurl -X PUT \"https://${HOST}${QUOTA_REST_PATH}/config/accounts/"
    "00000000-0000-4000-8000-000000000001\" --header 'X-Api-Version: 2' "
    "--data '{\"limit\":{\"type\":\"limited\",\"value\":5368709120}}'\n```",
    2: "Read it back with `/services/storage/admin/quota`.",
}


@pytest.mark.parametrize(
    "answer",
    [
        '`{"limit":{"type":"limited","value":VALUE}}`',
        '`{"limit":{"type":"limited","value":value_in_bytes}}`',
        '```json\n{\n  "limit": {"type": "limited", "value": <bytes>}\n}\n```',
    ],
)
def test_json_body_with_one_numeric_placeholder_is_kept(answer):
    assert guard_literal_code(answer, QUOTA_SCRIPT_SOURCE) == answer


@pytest.mark.parametrize(
    "answer",
    [
        # a path inferred by analogy or composed from two sources is not in any source
        "`/services/storage/admin/quota/config/cos/{id}`",
        "`/services/storage/admin/quota/config/accounts/{id}`",
        # new key, changed string, placeholder for a string leaf, two placeholders
        '`{"limit":{"type":"limited","value":VALUE,"unit":"B"}}`',
        '`{"limit":{"type":"unlimited","value":VALUE}}`',
        '`{"limit":{"type":TYPE,"value":5368709120}}`',
        '`{"limit":{"type":"limited","value":VALUE},"id":ID}`',
        '`{"limit":VALUE}`',
    ],
)
def test_inferred_paths_and_changed_json_bodies_stay_omitted(answer):
    assert guard_literal_code(answer, QUOTA_SCRIPT_SOURCE).startswith(OMISSION_MARKER)


def test_json_placeholder_count_ignores_json_literals():
    source = {1: '--data \'{"soft":4294967296,"hard":5368709120,"notify":true}\''}
    kept = '`{"soft":SOFT,"hard":5368709120,"notify":true}`'
    assert guard_literal_code(kept, source) == kept
    assert guard_literal_code('`{"soft":SOFT,"hard":HARD,"notify":true}`', source).startswith(
        OMISSION_MARKER
    )


def test_quote_style_mutation_is_replaced_by_the_source_literal():
    source = {1: "call(`x`)\nrun()"}
    guarded = guard_literal_code("Use `call('x')` here.", source)
    assert guarded == "Use `` call(`x`) `` here."
    assert OMISSION_MARKER not in guarded and "Original source excerpts" not in guarded


def test_quote_repair_restores_reflowed_table_cell_code_in_a_fence():
    answer = (
        "```js\n!d &&\n  j?.attrs?.acmeIsAdminAccount == 'TRUE' &&\n"
        "  (0, W.jsx)(X, {\n```\n"
    )
    guarded = guard_literal_code(answer, TABLE_CELL_SOURCE)
    assert guarded == (
        "```js\n!d && j?.attrs?.acmeIsAdminAccount == `TRUE` && (0, W.jsx)(X, {\n```\n"
    )


def test_quote_repair_needs_one_unambiguous_source_literal():
    two = {1: "set(`A`)", 2: 'set("A")'}
    assert OMISSION_MARKER in guard_literal_code("`set('A')`", two)
    changed = {1: "m(`label.view_mail`, `VIEW MAIL`)"}
    assert OMISSION_MARKER in guard_literal_code("`m('label.view', 'VIEW MAIL')`", changed)
    assert OMISSION_MARKER in guard_literal_code("`plain()`", {1: "other()"})


def test_code_repeated_from_an_earlier_answer_is_accepted():
    history = ["Install the tools:\n`apt install npm`\n`npm install prettier`"]
    answer = "Step 1: `apt install npm` then `npm install prettier`."
    assert guard_literal_code(answer, {1: "unrelated changelog"}, "improve", history) == answer


def test_history_does_not_admit_new_code_or_leak_into_the_source_section():
    history = ["Earlier: `apt install npm`"]
    guarded = guard_literal_code("Run `apt install -y npm`.", {1: "unrelated"}, "", history)
    assert OMISSION_MARKER in guarded
    assert "[[Source: 1]]" in guarded
    assert "Earlier:" not in guarded and "[[Source: -1]]" not in guarded


def test_citation_on_closing_fence_line_does_not_swallow_the_answer_tail():
    source = {19: "```\nacmectl backup doItemRestore {Account name or id} {item_id}\n```"}
    answer = (
        "Syntax:\n```\nacmectl backup doItemRestore {Account name or id} {item_id}\n"
        "``` [[Source: 19]]\n\nThen check the logs."
    )
    guarded = guard_literal_code(answer, source)
    assert OMISSION_MARKER not in guarded
    assert guarded == (
        "Syntax:\n```\nacmectl backup doItemRestore {Account name or id} {item_id}\n"
        "```\n[[Source: 19]]\n\nThen check the logs."
    )
    # A citation as the info string of an opening fence is not moved.
    assert guard_literal_code("``` [[Source: 1]]\nrun()\n```", {1: "run()"}).startswith(
        "``` [[Source: 1]]\nrun()"
    )


def test_inline_code_with_dropped_inner_backticks_is_replaced_by_the_source_literal():
    source = {1: "```\n--> : j?.attrs?.acmeIsDelegatedAdminAccount === `TRUE`\n```"}
    guarded = guard_literal_code("`j?.attrs?.acmeIsDelegatedAdminAccount === TRUE`", source)
    assert guarded == "`` j?.attrs?.acmeIsDelegatedAdminAccount === `TRUE` ``"
    guarded = guard_literal_code(
        "` !d &&     j?.attrs?.acmeIsAdminAccount == TRUE &&     (0, W.jsx)(X, { `",
        TABLE_CELL_SOURCE,
    )
    assert OMISSION_MARKER not in guarded and "`TRUE`" in guarded
    # A changed value is still omitted.
    assert OMISSION_MARKER in guard_literal_code(
        "`j?.attrs?.acmeIsDelegatedAdminAccount === FALSE`", source
    )
    # The literal backticks are content: the source text is restored, never the stripped one.
    assert guard_literal_code(
        "`m(label.view_mail, VIEW MAIL)`", {1: "m(`label.view_mail`, `VIEW MAIL`)"}
    ) == "`` m(`label.view_mail`, `VIEW MAIL`) ``"
