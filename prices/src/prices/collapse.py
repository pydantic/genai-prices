from .update import get_providers_yaml


def collapse():
    """Simplify prices by combining similar models."""
    providers_yaml = get_providers_yaml()
    total_combined = 0
    for provider_id, provider_yaml in providers_yaml.items():
        models = provider_yaml.provider.models
        combined = 0
        for child_index, child_model in enumerate(models):
            for parent_index, parent_model in enumerate(models):
                if not child_model.collapse:
                    continue
                elif child_index == parent_index:
                    continue
                elif not child_model.id.startswith(parent_model.id):
                    continue
                elif child_model.prices != parent_model.prices:
                    continue

                # prices are the same and parent_model's id matches the start of the child_model's id
                # e.g. something like `child_model.id = 'foobar:custom'`, `parent_model.id = 'foobar'`
                # so we want to merge child_model into parent_model and remove child_model

                provider_yaml.update_model(parent_model.id, child_model)
                provider_yaml.remove_model(child_model.id)
                combined += 1

        if combined:
            total_combined += combined
            print(f'Provider {provider_id}:')
            print(f'  {combined} models combined')
            print('')
            provider_yaml.save()

    if total_combined:
        print(f'Total models combined: {total_combined}')
    else:
        print('No models combined')
