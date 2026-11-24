"""Editable enemy profiles and exact combat probabilities for the Dice playtest."""
from functools import lru_cache


ARCHETYPES = ('Balanced', 'Striker', 'Tank')
BASE_BOSS_FACES = (1, 1, 2, 4, 7, 9)
DEFAULT_PROFILES = {
    '1': {'Striker': (7, (1, 1, 2, 2, 3, 4)), 'Balanced': (9, (0, 1, 1, 1, 3, 5)),
          'Tank': (13, (0, 0, 0, 0, 1, 4))},
    '2': {'Striker': (8, (0, 1, 3, 3, 4, 6)), 'Balanced': (9, (0, 0, 1, 4, 4, 6)),
          'Tank': (12, (0, 0, 1, 1, 1, 6))},
    '3': {'Striker': (9, (0, 0, 4, 5, 5, 8)), 'Balanced': (10, (0, 0, 1, 5, 6, 8)),
          'Tank': (12, (0, 0, 0, 1, 6, 7))},
}


def profile_defaults():
    return {zone: {name: dict(hp=hp, faces=list(faces)) for name, (hp, faces) in profiles.items()}
            for zone, profiles in DEFAULT_PROFILES.items()}


def validate_profiles(profiles):
    if not isinstance(profiles, dict) or set(profiles) != set(DEFAULT_PROFILES):
        raise ValueError('Enemy profiles require Zones 1, 2, and 3.')
    for group in profiles.values():
        if not isinstance(group, dict) or set(group) != set(ARCHETYPES):
            raise ValueError('Each zone needs Balanced, Striker, and Tank profiles.')
        for profile in group.values():
            if (not isinstance(profile, dict) or set(profile) != {'hp', 'faces'}
                    or type(profile['hp']) is not int or not 1 <= profile['hp'] <= 100):
                raise ValueError('Enemy HP must be a whole number from 1 to 100.')
            faces = profile['faces']
            if (not isinstance(faces, list) or len(faces) != 6
                    or any(type(hit) is not int or not 0 <= hit <= 20 for hit in faces)):
                raise ValueError('Enemy attack needs six whole numbers from 0 to 20.')


def shield_block(settings, level):
    if settings.rolled_enemy_attacks:
        return (0, 2, 3, 5)[level]
    return settings.shield_block_per_level * level


def boss_faces(settings):
    return tuple(max(0, settings.boss_attack + value - 4) for value in BASE_BOSS_FACES)


def archetype_counts(count):
    return tuple(count // 3 + int(i < count % 3) for i in range(3))


@lru_cache(maxsize=65536)
def fight_odds(hp, energy, bonus, grenade, hits):
    """Return (win probability, expected Energy lost), averaging both d6 rolls."""
    wins = loss = 0.0
    for player_die in range(1, 7):
        hp_left = hp - player_die - bonus - grenade
        if hp_left <= 0:
            wins += 1
            continue
        for hit in hits:
            loss += min(energy, hit) / 6
            if hit and hit >= energy:
                continue
            win, later_loss = fight_odds(hp_left, energy-hit, bonus, 0, hits)
            wins += win / 6
            loss += later_loss / 6
    return wins / 6, loss / 6


def odds_table(settings):
    rows = []
    for zone in (1, 2, 3):
        group = settings.monster_profiles[str(zone)]
        sword = zone + settings.sword_damage_bonus
        block = shield_block(settings, zone)
        for name in ARCHETYPES:
            profile = group[name]
            for energy in (1, 2, 4, 6, 8):
                wins = [fight_odds(profile['hp'], energy, bonus, 0,
                                   tuple(max(0, raw-guard) for raw in profile['faces']))[0]
                        for bonus, guard in ((0, 0), (sword, 0), (0, block), (sword, block))]
                rows.append(dict(zone=zone, archetype=name, energy=energy, wins=wins))
    return rows
