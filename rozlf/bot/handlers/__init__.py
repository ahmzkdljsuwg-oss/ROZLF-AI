from . import analysis, auto, commands, image, menu, settings, signals, stats

ROUTERS = (
    commands.router,
    menu.router,
    auto.router,
    analysis.router,
    signals.router,
    stats.router,
    settings.router,
    image.router,
)
