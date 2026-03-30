from src.core.tenants.application.effective_config import (
    merge_rule_lists,
    merge_tenant_config,
    resolve_rag_prompts,
)


def test_merge_tenant_config_inherits_defaults_but_not_active_collection():
    default_config = {
        'rag_system_prompt': 'DEFAULT_SYSTEM',
        'llm_provider': 'openai',
        'active_vector_collection': 'document_chunks',
        'llm_steps': {
            'chat.generation': {
                'temperature': 0.1,
                'provider': 'openai',
            }
        },
    }
    tenant_config = {
        'rag_user_prompt': 'TENANT_USER: {query}',
        'llm_steps': {
            'chat.generation': {
                'seed': 99,
            }
        },
    }

    merged = merge_tenant_config(default_config, tenant_config)

    assert merged['rag_system_prompt'] == 'DEFAULT_SYSTEM'
    assert merged['rag_user_prompt'] == 'TENANT_USER: {query}'
    assert merged['llm_provider'] == 'openai'
    assert merged['llm_steps']['chat.generation']['temperature'] == 0.1
    assert merged['llm_steps']['chat.generation']['provider'] == 'openai'
    assert merged['llm_steps']['chat.generation']['seed'] == 99
    assert 'active_vector_collection' not in merged


def test_merge_rule_lists_keeps_default_rules_first():
    merged = merge_rule_lists(['default-1', 'default-2'], ['tenant-1'])
    assert merged == ['default-1', 'default-2', 'tenant-1']


def test_resolve_rag_prompts_appends_rules_after_tenant_override():
    system_prompt, user_prompt = resolve_rag_prompts(
        base_system_prompt='BASE_SYSTEM',
        base_user_prompt='BASE_USER: {query}',
        tenant_config={
            'rag_system_prompt': 'TENANT_SYSTEM',
            'rag_user_prompt': 'TENANT_USER: {query}',
        },
        rules_addendum='\n\n## DOMAIN RULES\n- rule',
    )

    assert system_prompt.startswith('TENANT_SYSTEM')
    assert '## DOMAIN RULES' in system_prompt
    assert user_prompt == 'TENANT_USER: {query}'
