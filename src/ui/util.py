from datetime import datetime
import functools

import dearpygui.dearpygui as dpg

from ..app_types import *

def prettydate(d: datetime) -> str:
    # https://stackoverflow.com/a/5164027
    delta = datetime.now() - d
    s = delta.seconds
    if delta.days > 7 or delta.days < 0:
        return d.strftime('%d %b %y')
    elif delta.days == 1:
        return '1 day ago'
    elif delta.days > 1:
        return '{} days ago'.format(delta.days)
    elif s <= 1:
        return 'just now'
    elif s < 60:
        return '{} seconds ago'.format(s)
    elif s < 120:
        return '1 minute ago'
    elif s < 3600:
        return '{} minutes ago'.format(s/60)
    elif s < 7200:
        return '1 hour ago'
    else:
        return '{} hours ago'.format(s/3600)


@functools.lru_cache
def make_node_theme_for_hue(hue: AppColor) -> DpgTag:
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvNode):
            dpg.add_theme_color(dpg.mvNodeCol_TitleBar, hue.set_hsv(s=0.5, v=0.4).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_TitleBarHovered, hue.set_hsv(s=0.5, v=0.5).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_TitleBarSelected, hue.set_hsv(s=0.4, v=0.55).to_rgb24(), category=dpg.mvThemeCat_Nodes)

            dpg.add_theme_color(dpg.mvNodeCol_NodeBackground, hue.set_hsv(s=0.15, v=0.3).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundHovered, hue.set_hsv(s=0.1, v=0.35).to_rgb24(), category=dpg.mvThemeCat_Nodes)
            dpg.add_theme_color(dpg.mvNodeCol_NodeBackgroundSelected, hue.set_hsv(s=0.1, v=0.35).to_rgb24(), category=dpg.mvThemeCat_Nodes)
    return theme
