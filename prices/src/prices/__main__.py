import sys
from inspect import getdoc

from .build import build
from .collapse import collapse
from .detect_deprecated import detect_deprecated
from .inject_providers import inject_providers
from .package_data import package_data
from .price_discrepancies import check_for_price_discrepancies, update_price_discrepancies
from .source_anthropic import get_anthropic_prices
from .source_arcee import get_arcee_prices
from .source_avian import get_avian_prices
from .source_aws import get_aws_prices
from .source_azure import get_azure_prices
from .source_baseten import get_baseten_prices
from .source_cerebras import get_cerebras_prices
from .source_cloudflare import get_cloudflare_prices
from .source_cursor import get_cursor_prices
from .source_databricks import get_databricks_prices
from .source_doubleword import get_doubleword_prices
from .source_fireworks import get_fireworks_prices
from .source_github_copilot import get_github_copilot_prices
from .source_google import get_google_prices
from .source_groq import get_groq_prices
from .source_huggingface import get_huggingface_prices
from .source_litellm import get_litellm_prices
from .source_meta import get_meta_prices
from .source_minimax import get_minimax_prices
from .source_mistral import get_mistral_prices
from .source_modal import get_modal_prices
from .source_moonshotai import get_moonshotai_prices
from .source_novita import get_novita_prices
from .source_openai import get_openai_prices
from .source_openai_decisions import get_openai_decisions_prices
from .source_openrouter import get_openrouter_prices, get_openrouter_provider_prices, update_from_openrouter
from .source_ovhcloud import get_ovhcloud_prices
from .source_perplexity import get_perplexity_prices
from .source_quicksilverpro import get_quicksilverpro_prices
from .source_simonw_prices import get_simonw_prices
from .source_together import get_together_prices
from .source_typesafe import get_typesafe_prices
from .source_voyageai import get_voyageai_prices
from .source_xai import get_xai_prices
from .source_zai import get_zai_prices


def main():
    actions = (
        build,
        update_from_openrouter,
        collapse,
        detect_deprecated,
        get_anthropic_prices,
        get_arcee_prices,
        get_avian_prices,
        get_azure_prices,
        get_aws_prices,
        get_baseten_prices,
        get_cerebras_prices,
        get_cloudflare_prices,
        get_cursor_prices,
        get_databricks_prices,
        get_doubleword_prices,
        get_fireworks_prices,
        get_github_copilot_prices,
        get_google_prices,
        get_groq_prices,
        get_huggingface_prices,
        get_litellm_prices,
        get_meta_prices,
        get_minimax_prices,
        get_mistral_prices,
        get_modal_prices,
        get_moonshotai_prices,
        get_novita_prices,
        get_openai_prices,
        get_openai_decisions_prices,
        get_openrouter_prices,
        get_openrouter_provider_prices,
        get_ovhcloud_prices,
        get_perplexity_prices,
        get_quicksilverpro_prices,
        get_simonw_prices,
        get_together_prices,
        get_typesafe_prices,
        get_voyageai_prices,
        get_xai_prices,
        get_zai_prices,
        update_price_discrepancies,
        check_for_price_discrepancies,
        package_data,
        inject_providers,
    )
    if len(sys.argv) == 2:
        command = sys.argv[1]
        if command == 'check_for_price_discrepancies':
            sys.exit(int(check_for_price_discrepancies() > 0))
        action = next((f for f in actions if f.__name__ == command), None)
        if action:
            action()
            return
        else:
            print('Invalid command')

    print('Usage: uv run -m src [action]')
    print('actions:')
    for f in actions:
        doc = (getdoc(f) or '').split('\n', 1)[0]
        print(f'  {f.__name__}: {doc}')
    sys.exit(1)


if __name__ == '__main__':
    main()
