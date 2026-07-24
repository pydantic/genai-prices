from prices import build as build_module


def test_provider_yaml_schema_suggests_registry_price_keys_from_units() -> None:
    schema = build_module._provider_yaml_schema(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            },
        }
    )

    model_price_schema = schema['$defs']['ModelPrice']
    properties = model_price_schema['properties']
    assert properties['input_mtok']['description'] == 'price in USD per million uncached text input/prompt token'
    assert properties['sausage_mtok'] == model_price_schema['additionalProperties']
    assert isinstance(model_price_schema['additionalProperties'], dict)


def test_provider_yaml_schema_includes_current_dynamic_registry_price_keys() -> None:
    schema = build_module._provider_yaml_schema(build_module.load_units())

    properties = schema['$defs']['ModelPrice']['properties']
    assert 'cache_image_read_mtok' in properties


def test_provider_yaml_schema_suggests_extractor_dests_from_reported_registry_units() -> None:
    schema = build_module._provider_yaml_schema(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            },
            'requests': {
                'per': 1_000,
                'price_key': 'requests_kcount',
                'dimensions': {'family': 'requests'},
            },
        }
    )

    dest_schema = schema['$defs']['UsageExtractorMapping']['properties']['dest']
    assert dest_schema['enum'] == ['input_tokens', 'sausage_tokens']
    assert 'requests' not in dest_schema['enum']
