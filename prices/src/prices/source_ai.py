from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys

import httpx
from bs4 import BeautifulSoup, Comment, Tag
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from . import source_prices, types, update, utils

zenrows_api_key = os.environ['ZENROWS_API_KEY']


def get_ai_prices():
    """Retrieves AI prices for a given provider using zenrows.com and Pydantic AI."""
    if len(sys.argv) == 3:
        provider_id = sys.argv[2]
    else:
        provider_id = input('Enter provider id: ')
    providers_yml = update.get_providers_yaml()
    provider = providers_yml[provider_id].provider
    provider_prices = asyncio.get_event_loop().run_until_complete(update_get_provider(provider))

    source_prices.write_source_prices('ai', {provider_id: provider_prices})


async def update_get_provider(provider: types.Provider) -> source_prices.ProvidePrices:
    if not provider.pricing_urls:
        print(f'No pricing URLs found for {provider.name}')
        return {}
    model_ids = [model.id for model in provider.models]
    provider_prices: source_prices.ProvidePrices = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for pricing_url in provider.pricing_urls:
            extra_prices = await update_get_provider_page(client, str(pricing_url), model_ids)
            provider_prices.update(extra_prices)

    return provider_prices


async def update_get_provider_page(
    client: httpx.AsyncClient, url: str, model_ids: list[str]
) -> source_prices.ProvidePrices:
    html = await cache_get(client, url)

    content_id = None
    if m := re.search('#(.+)', url):
        content_id = m.group(1)

    cleaned_html = clean_html(html, content_id)

    result = await html_agent.run(cleaned_html, deps=AgentDeps(known_model_ids=model_ids))
    provider_prices = {m.id: m.prices for m in result.output.models if not m.prices.is_free()}
    print(f'{url} found {len(provider_prices)} models')

    return provider_prices


fetch_directly = {
    # this URl is blocked by zenrows but is rendered as HTML anyway
    'https://ai.google.dev/gemini-api/docs/pricing',
}


async def cache_get(client: httpx.AsyncClient, url: str):
    cache_dir = utils.root_dir / '.html_cache'
    cache_dir.mkdir(exist_ok=True)

    cache_file = cache_dir / f'{hashlib.md5(url.encode()).hexdigest()}.html'
    if cache_file.exists():
        return cache_file.read_text()
    else:
        if url in fetch_directly:
            print(f'getting content from {url} directly...')
            response = await client.get(url)
        else:
            print(f'getting content from {url} with zenrows...')
            params = {'url': url, 'apikey': zenrows_api_key, 'js_render': 'true'}
            response = await client.get('https://api.zenrows.com/v1/', params=params)

        if not response.is_success:
            raise ValueError(f'Failed to get content from {url} -> {response.status_code}:\n{response.text}')
        html = response.text
        cache_file.write_text(html)
        return html


class _Model(BaseModel, extra='forbid', use_attribute_docstrings=True):
    """Custom abstract based model with config"""


class ModelInfo(_Model):
    """Information about an LLM model"""

    id: str
    """Primary unique identifier for the model"""
    # name: str | None = None
    # """Name of the model"""
    # aliases: list[str] | None = None
    # """Alternative IDs for the model"""
    # context_window: int | None = None
    # """Maximum number of input tokens allowed for this model"""
    prices: types.ModelPrice


class ProviderPricingPage(_Model):
    """Pricing page for a provider"""

    models: list[ModelInfo] = Field(default_factory=list)
    """List of models with information"""


class AgentDeps(BaseModel):
    known_model_ids: list[str]


html_agent = Agent(
    'anthropic:claude-sonnet-4-0',
    output_type=ProviderPricingPage,
    deps_type=AgentDeps,
    instructions="""\
Your job is to inspect the HTML page and extract information about all LLM models included in the page,
either information about the models or links to pages with more details about the models.

If information about a model exists (model_infos), do NOT include it in model_links.

These are the models we already know of, if you find models matching these IDs, make sure
to use these IDs, otherwise use the most appropriate ID for the model which should approxmiately match this format:
""",
)


@html_agent.instructions
def add_known_model_ids(ctx: RunContext[AgentDeps]) -> str:
    return '\n'.join(ctx.deps.known_model_ids)


keep_htmls_attrs = {'id', 'href', 'type', 'src'}


def clean_html(html: str, content_id: str | None = None) -> str:
    print(f'full page size: {len(html)}')
    # Parse the HTML content
    page_soup = BeautifulSoup(html, 'html.parser')

    if content_id is not None:
        soup = page_soup.find(id=content_id)
        assert isinstance(soup, Tag), f'Content with id {content_id} not found'
    else:
        # Extract the body
        soup = page_soup.body
        assert soup is not None, 'body not found'

    # Remove all script and svg tags
    for script_or_svg in soup(['script', 'svg']):
        script_or_svg.decompose()

    # Remove all class attributes
    for tag in soup.find_all(True):
        assert isinstance(tag, Tag)
        if not tag.contents:
            tag.decompose()
            continue

        # If tag has only one child, replace it with the child
        if len(tag.contents) == 1 and isinstance(tag.contents[0], Tag):
            child = tag.contents[0]
            tag.replace_with(child)

    for tag in soup.find_all(True):
        assert isinstance(tag, Tag)
        for key in list(tag.attrs):
            if key not in keep_htmls_attrs:
                del tag.attrs[key]

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        assert isinstance(comment, Comment)
        # If the comment is empty or contains only whitespace, remove it
        stripped = comment.strip()
        if len(stripped) <= 2:
            comment.decompose()

    # pretty_html = body.prettify(formatter='html')
    # assert isinstance(pretty_html, str)
    compact_content = str(soup)
    print('size after cleaning:', len(compact_content))

    return compact_content
