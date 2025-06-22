from .update import get_providers_yaml


def simplify():
    """Simplify prices by combining similar models."""
    providers_yaml = get_providers_yaml()
    for provider_id, provider_yaml in providers_yaml.items():
        models = provider_yaml.provider.models
        combined = 0
        for index, model in enumerate(models):
            for comp_index, comp_model in enumerate(models):
                if index == comp_index:
                    continue
                if not model.id.startswith(comp_model.id):
                    continue
                if model.prices != comp_model.prices:
                    continue

                # prices are the same and comp_model's is similar to model's
                # e.g. something like `model_id = 'foobar:custom'`, `comp_model_id = 'foobar'`
                # so we want to merge model into comp_model and remove model

                provider_yaml.update_model(comp_model.id, model)
                provider_yaml.remove_model(model.id)
                combined += 1

        if combined:
            print(f'Provider {provider_id}:')
            print(f'  {combined} models combined')
            print('')
            provider_yaml.save()
