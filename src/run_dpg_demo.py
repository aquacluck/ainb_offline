import dearpygui.dearpygui as dpg
import dearpygui.demo as demo


dpg.create_context()
demo.show_demo()
dpg.create_viewport(title="dpg demo", x_pos=0, y_pos=0, width=1600, height=1080, decorated=True, vsync=True)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.maximize_viewport()
dpg.show_viewport(maximized=True)
dpg.destroy_context()
