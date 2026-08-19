"""
Regression tests for DataSnapshot._lookup_cache read/write key symmetry.

Paper derivation (no execution needed to predict either failure): calc_price(usage,
model_ref=M) with no provider_id/provider_api_url is, by construction, a pure function
of (snapshot, M): DataSnapshot.calc -> find_provider_model(M, None, None, None), whose
`else` branch resolves the provider via find_provider, which (find_provider_model /
find_provider, data_snapshot.py) picks the FIRST provider in `providers` whose
model_match matches M. That does not depend on any earlier call, so an isolated
calc_price call and one preceded by an unrelated, provider-qualified extract_usage call
must agree on provider.id and total_price.

Before the fix, find_provider_model's single cache-write statement used
(provider_id, provider_api_url, model_ref) unconditionally -- the *parameters*, not
`provider.id` -- even on the branch where a `provider` object was supplied positionally
(the extract_usage path, which always passes provider_id=None, provider_api_url=None).
The write therefore landed on (None, None, model_ref): exactly the key the provider-less
branch reads. A prior extract_usage(..., provider_id=X) call poisons every later
provider-less calc_price(model_ref=M) in the same process/snapshot.
"""

from genai_prices import Usage
from genai_prices.data import providers
from genai_prices.data_snapshot import DataSnapshot, find_provider_by_id

# Both 'anthropic' and 'google' define this model id (prices/providers/anthropic.yml,
# prices/providers/google.yml) at *different* rates, so a wrong provider selection is
# visible both as provider.id and as a different total_price. Neither assertion below
# hardcodes a rate, so a price update does not touch this test -- it only needs the id
# to stay defined by two providers that disagree on the price.
SHARED_MODEL_REF = 'claude-opus-4-6'


def test_calc_price_order_independent_of_preceding_extract_usage():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)

    baseline_snapshot = DataSnapshot(providers=providers, from_auto_update=False)
    baseline = baseline_snapshot.calc(usage, SHARED_MODEL_REF, None, None, None)

    poisoned_snapshot = DataSnapshot(providers=providers, from_auto_update=False)
    # Unrelated, explicitly provider-qualified extraction, e.g. handling a Google/Vertex
    # webhook payload, that happens to name the same model id.
    poisoned_snapshot.extract_usage(
        {
            'modelVersion': SHARED_MODEL_REF,
            'usageMetadata': {'promptTokenCount': 1, 'candidatesTokenCount': 1},
        },
        provider_id='google',
    )

    after = poisoned_snapshot.calc(usage, SHARED_MODEL_REF, None, None, None)

    assert after.provider.id == baseline.provider.id, (
        'calc_price(usage, model_ref=...) with no provider must not depend on a preceding, '
        'unrelated extract_usage(..., provider_id=...) call for the same model_ref'
    )
    assert after.total_price == baseline.total_price


def test_supplied_provider_read_key_is_written():
    """
    The branch taken when `provider` is supplied positionally reads
    (provider.id, None, model_ref). For the memo to ever hit on that branch, a
    successful lookup there must write that same key. Before the fix, the write used
    (provider_id, provider_api_url, model_ref) -- (None, None, model_ref) on this call
    path -- so the read key was never populated by anything and this branch's memo was
    decorative.
    """
    google_provider = find_provider_by_id(providers, 'google')
    assert google_provider is not None

    snap = DataSnapshot(providers=providers, from_auto_update=False)
    snap.find_provider_model(SHARED_MODEL_REF, google_provider, None, None)

    assert (google_provider.id, None, SHARED_MODEL_REF) in snap._lookup_cache
