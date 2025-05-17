import os
import csv # For CSV handling
import threading
import time
import json
import socket

# GUIライブラリのインポート (GUI Library Imports)
from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.config import Config
from kivy.core.window import Window
Config.set('graphics', 'maxfps', 60)

# GUIコンポーネント関連 (GUI Component Related)
from kivymd.uix.card import MDCard
from kivymd.uix.button import MDButton, MDIconButton, MDButtonText # MDTextButton は使用せず MDButton(MDButtonText) 形式に
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.navigationdrawer import MDNavigationDrawerItem, MDNavigationDrawerItemText
from kivymd.uix.dialog import MDDialog, MDDialogHeadlineText, MDDialogContentContainer, MDDialogButtonContainer # Dialog構成要素をインポート
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.textfield import MDTextField
from kivymd.uix.label import MDLabel
from kivy.uix.widget import Widget # MDDialogButtonContainerのスペーサー用

# Kivyプロパティ (Kivy Properties)
from kivy.properties import StringProperty, ListProperty, BooleanProperty, NumericProperty, ObjectProperty

# Kivyフォント関連 (Kivy Font Related)
from kivy.core.text import LabelBase, DEFAULT_FONT
fontdir = os.path.join(os.path.dirname(__file__), 'font', 'NotoSansJP-Regular.ttf')
rootdir = os.path.dirname(__file__)
LabelBase.register(DEFAULT_FONT, fontdir)

# グラフ描画関連 (Graph Drawing Related)
import numpy as np
from kivy.clock import Clock
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
import matplotlib
matplotlib.use('Agg')   # 非アクティブになる現象を抑止 (Suppress inactive phenomenon)
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont(fontdir) #matplotlib
plt.rc('font', family="Noto Sans JP")

# 画面遷移関連 (Screen Transition Related)
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from functools import partial

# スレッドイベント (Threading Events)
stop_event = threading.Event()
csv_stop_event = threading.Event()

class StartScreen(MDScreen):
    def on_connect_button_press(self):
        app = MDApp.get_running_app()
        app.start_communication()

class MainScreen(MDScreen):
    def on_disconnect_button_press(self):
        app = MDApp.get_running_app()
        app.stop_communication("Disconnected!")

class PageManager(MDScreenManager):
    pass
    
class NativeGUIApp(MDApp):
    Builder.load_file(os.path.join(rootdir, 'layout.kv'))
    trans_data =  '' 
    selected_actuater = StringProperty("0") 
    add_cylinder_num = 0 
    
    # CSV Playback Properties
    csv_file_path = StringProperty("")
    loaded_csv_filename = StringProperty("No CSV loaded")
    csv_data = ListProperty([])
    is_csv_playing = BooleanProperty(False)
    loop_csv = BooleanProperty(False)
    current_csv_row_index = NumericProperty(0)
    csv_playback_thread = ObjectProperty(None, allownone=True)
    _file_path_input_dialog = ObjectProperty(None, allownone=True)

    # Slider properties
    slider_position = StringProperty("2000") 
    slider_command = StringProperty("2000")  
    before_slider_position = StringProperty("2000")
    before_slider_command = StringProperty("2000")

    # Sensor data
    position = 0 
    voltage = 0  
    command = 0
    p = 0.0 
    i = 0.0
    d = 0.0
    capture_max = None
    capture_min = None
    
    def build(self):    
        self.screen_manager = PageManager()
        self.settings_manager = SettingsManager()
        
        self.theme_cls.theme_style_switch_animation = True
        self.theme_cls.theme_style = self.settings_manager.get_setting('theme', 'Light')
        self.theme_cls.primary_palette = self.settings_manager.get_setting('color', 'Green')
        self.actuater_name = self.settings_manager.get_setting('actuater_name', {})
        self.selected_actuater = str(self.settings_manager.get_setting('selected_actuater_default', '0'))

        self.loop_csv = self.settings_manager.get_setting('csv_loop_enabled', False)
        last_path = self.settings_manager.get_setting('last_csv_path', "")
        if last_path and os.path.exists(last_path):
            self.csv_file_path = last_path
            self.loaded_csv_filename = os.path.basename(last_path)
        else:
            self.csv_file_path = ""
            self.loaded_csv_filename = "No CSV loaded"

        self.screen_manager.get_screen('start').ids.address_field.text = self.settings_manager.get_setting('address', 'localhost')
        self.connect_button = self.screen_manager.get_screen('start').ids.connect_button
        self.address_field = self.screen_manager.get_screen('start').ids.address_field
        self.progressindicator = self.screen_manager.get_screen('start').ids.progressindicator
        
        main_screen_ids = self.screen_manager.get_screen('main').ids
        self.graph_area = main_screen_ids.graph_area
        self.input_switch = main_screen_ids.input_switch
        self.position_switch = main_screen_ids.position_switch
        self.voltage_switch = main_screen_ids.voltage_switch
        self.command_switch = main_screen_ids.command_switch
        self.navigation_drawer = main_screen_ids.nav_drawer_menu

        self.gain_reload = main_screen_ids.gain_reload
        self.p_field = main_screen_ids.gain_p
        self.i_field = main_screen_ids.gain_i
        self.d_field = main_screen_ids.gain_d
        self.gain_send = main_screen_ids.gain_send
        self.save_button = main_screen_ids.gain_save
        self.position_slider = main_screen_ids.position_slider
        self.command_slider = main_screen_ids.command_slider
        self.offset_capture = main_screen_ids.offset_capture
        self.stroke_capture = main_screen_ids.stroke_capture
        
        self.play_stop_csv_button = main_screen_ids.play_stop_csv_button
        self.loop_csv_switch = main_screen_ids.loop_csv_switch
        self.loop_csv_switch.active = self.loop_csv 
        self.loaded_csv_filename_label = main_screen_ids.loaded_csv_filename_label
        self.loaded_csv_filename_label.text = self.loaded_csv_filename
        
        self.udp_thread = None        
        self._added_actuators_to_drawer = set() 
        return self.screen_manager
    
    def on_start(self): 
        Window.maximize()
        self.screen_manager.get_screen('main').ids.nav_drawer.set_state("open")
        self.fig = plt.figure() 
        self.fig, self.ax = plt.subplots()
        self.apply_theme_to_plot()

        if self.csv_file_path and os.path.exists(self.csv_file_path):
            self._load_csv_data(self.csv_file_path)
        else: 
            self.play_stop_csv_button.disabled = True
            self.loaded_csv_filename = "No CSV loaded"
            if hasattr(self, 'loaded_csv_filename_label'): 
                 self.loaded_csv_filename_label.text = self.loaded_csv_filename
    
    def on_stop(self):  
        stop_event.set()
        csv_stop_event.set() 
        if self.csv_playback_thread and self.csv_playback_thread.is_alive():
            self.csv_playback_thread.join(timeout=0.5) 
        if self.udp_thread and self.udp_thread.is_alive():
            self.udp_thread.join(timeout=0.5)
        self.settings_manager.save_settings() 
        return True
    
    def start_communication(self):
        address_field = self.screen_manager.get_screen('start').ids.address_field
        self.address = address_field.text
        try:
            self.dynamicUdpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except socket.error as e:
            self.show_snackbar(f"Socket creation error: {e}")
            return
        self.udp_thread = None 
        stop_event.clear() 
        if not self.udp_thread: 
            self.udp_thread = threading.Thread(target=self.udp_receiver, args=(self.address,))
            self.udp_thread.daemon = True 
            self.udp_thread.start()

    def stop_communication(self, message):
        if self.is_csv_playing: 
            self.toggle_csv_playback() 
        self.change_screen('start')
        self.connect_button.disabled = False
        self.address_field.disabled = False
        self.progressindicator.active = False
        self.position_slider.disabled = True
        self.command_slider.disabled = True
        self.offset_capture.disabled = True
        self.stroke_capture.disabled = True
        self.gain_reload.disabled = True
        self.switch_gain_window(True)
        if hasattr(self, 'update_event') and self.update_event: 
            Clock.unschedule(self.update_event)
            self.update_event = None 
        if self.navigation_drawer: 
            self.navigation_drawer.clear_widgets() 
        self._added_actuators_to_drawer.clear()
        if hasattr(self.graph_area, 'clear_widgets'): 
            self.graph_area.clear_widgets() 
        self.selected_actuater = str(self.settings_manager.get_setting('selected_actuater_default', '0'))
        self.add_cylinder_num = 0 
        stop_event.set() 
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            try:
                self.dynamicUdpSocket.close()
            except Exception as e:
                print(f"Error closing dynamicUdpSocket: {e}")
            self.dynamicUdpSocket = None 
        if hasattr(self, 'udp_socket') and self.udp_socket: 
            try:
                self.udp_socket.close()
            except Exception as e:
                print(f"Error closing udp_socket: {e}")
            self.udp_socket = None 
        Clock.schedule_once(lambda dt: self.show_snackbar(message)) 
    
    def udp_receiver(self,address_arg): 
        self.settings_manager.update_setting('address', self.address_field.text)
        Clock.schedule_once(lambda dt: setattr(self.connect_button, 'disabled', True))
        Clock.schedule_once(lambda dt: setattr(self.address_field, 'disabled', True))
        Clock.schedule_once(lambda dt: setattr(self.progressindicator, 'active', True))
        print("UDPサーバーに接続中")
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.settimeout(3.0)
            self.udp_socket.bind(("0.0.0.0", 6050))
            print("UDPでサーバーからのメッセージを受信中...")
            initial_data_received = False
            while not stop_event.is_set():
                try:
                    data, addr = self.udp_socket.recvfrom(4096)
                    receive_data = data.decode('utf-8', errors='ignore')
                    self.trans_data = json.loads(receive_data)
                    if self.trans_data.get('type') == "current_sensor_value":
                        initial_data_received = True 
                        break 
                except socket.timeout:
                    print("Waiting for initial data from server (timeout)...")
                    if stop_event.is_set(): break
                    continue
                except json.JSONDecodeError as je:
                    print(f"JSON Decode Error (initial): {je} - Data: '{receive_data}'")
                except Exception as e: 
                    print(f"Error during initial data reception: {e}")
                    Clock.schedule_once(lambda x, err_msg=str(e): self.stop_communication(f"Connection Error: {err_msg}"))
                    return
            if not initial_data_received and not stop_event.is_set(): 
                Clock.schedule_once(lambda x: self.stop_communication("Failed to receive initial sensor data."))
                return
            if not stop_event.is_set(): 
                print(f"Connected: {addr}")
                Clock.schedule_once(lambda x: self.change_screen('main'))
            self.add_cylinder_num = 0 
            self._added_actuators_to_drawer.clear()
            current_num_for_drawer = 0 
            while not stop_event.is_set():
                try:              
                    data, addr = self.udp_socket.recvfrom(4096)
                except socket.timeout: 
                    if stop_event.is_set(): break
                    continue
                except Exception as e: 
                    if not stop_event.is_set():
                        print(f"UDP recv error during operation: {e}")
                    break 
                receive_data = data.decode('utf-8', errors='ignore')
                try:
                    self.trans_data = json.loads(receive_data)
                except json.JSONDecodeError as je:
                    print(f"JSON Decode Error (loop): {je} - Data: '{receive_data}'")
                    continue 
                msg_type = self.trans_data.get('type')
                if msg_type == "current_sensor_value":
                    sensors_data = self.trans_data.get("sensors", [])
                    if sensors_data:
                        first_sensor_num_str = str(sensors_data[0].get("num", -1))
                        if first_sensor_num_str == str(current_num_for_drawer):
                            Clock.schedule_once(lambda dt: self.update_drawer_menu())
                            current_num_for_drawer +=1
                        try:
                            selected_act_int = int(self.selected_actuater)
                            self.position = next((s.get('position') for s in sensors_data if s.get('num') == selected_act_int), self.position)
                            self.voltage = next((s.get('voltage') for s in sensors_data if s.get('num') == selected_act_int), self.voltage)
                            self.command = next((s.get('command') for s in sensors_data if s.get('num') == selected_act_int), self.command)
                        except ValueError: 
                            pass
                elif msg_type == "response_gain_value":
                    cylinder_num_str = str(self.trans_data.get("num")) 
                    if cylinder_num_str == self.selected_actuater: 
                        gains = self.trans_data.get("gains", {})
                        self.p = gains.get("p", self.p) 
                        self.i = gains.get("i", self.i)
                        self.d = gains.get("d", self.d)
                        self.capture_max = self.trans_data.get("capture", {}).get("max", self.capture_max)
                        self.capture_min = self.trans_data.get("capture", {}).get("min", self.capture_min)
                        Clock.schedule_once(lambda x: self.gain_sync(self.p, self.i, self.d))
            if hasattr(self, 'udp_socket') and self.udp_socket: 
                self.udp_socket.close()
            self.udp_socket = None 
            print("切断しました (UDP receiver stopped)")
        except socket.timeout: 
             error_message = "UDP Connection Timeout. No data received."
             print(error_message)
             Clock.schedule_once(lambda x: self.stop_communication(error_message))
        except Exception as e:
            error_message = f"UDP Communication Error in receiver: {e}"
            print(error_message)
            if not stop_event.is_set(): 
                 Clock.schedule_once(lambda x, emsg=error_message: self.stop_communication(emsg))
        finally:
            Clock.schedule_once(lambda dt: setattr(self.connect_button, 'disabled', False))
            Clock.schedule_once(lambda dt: setattr(self.address_field, 'disabled', False))
            Clock.schedule_once(lambda dt: setattr(self.progressindicator, 'active', False))

    def change_screen(self, screen_name):
        self.root.current = screen_name
    
    def switch_gain_window(self, switch):
        self.p_field.disabled = switch
        self.i_field.disabled = switch
        self.d_field.disabled = switch
        self.gain_send.disabled = switch
        self.save_button.disabled = switch
        
    def gain_request(self):     
        if not hasattr(self, 'dynamicUdpSocket') or not self.dynamicUdpSocket:
            return
        self.switch_gain_window(True)
        try:
            num_to_send = int(self.selected_actuater)
            data = {"type": "request_gain_value", "num": num_to_send}
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
            print(f"Sent gain request: {data}")
        except ValueError:
            self.show_snackbar("Invalid actuator ID for gain request.")
        except socket.error as e:
            self.show_snackbar(f"UDP Send Error: {e}")

    def gain_sync(self,p_val,i_val,d_val):
        self.p_field.text = str(p_val if p_val is not None else "")
        self.i_field.text = str(i_val if i_val is not None else "")
        self.d_field.text = str(d_val if d_val is not None else "")
        self.switch_gain_window(False)
        
    def fixed_motion(self,motion_type):     
        if not hasattr(self, 'dynamicUdpSocket') or not self.dynamicUdpSocket:
            self.show_snackbar("Not connected. Cannot send fixed motion.")
            return
        data = {"type": "fixed_motion", "motion": motion_type}
        try:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
            self.show_snackbar(f"Fixed motion requesting... ⇒ {motion_type}")
            print(f"Sent fixed motion: {data}")
        except socket.error as e:
            self.show_snackbar(f"UDP Send Error: {e}")
        
    def gain_change(self):    
        if not hasattr(self, 'dynamicUdpSocket') or not self.dynamicUdpSocket:
            self.show_snackbar("Not connected. Cannot change gain.")
            return
        try:
            p_val = float(self.p_field.text)
            i_val = float(self.i_field.text)
            d_val = float(self.d_field.text)
            num_to_send = int(self.selected_actuater) 
        except ValueError:
            self.show_snackbar("Invalid gain values or actuator ID.")
            return
        self.switch_gain_window(True)
        data = {"type": "set_gain_value", "num": num_to_send, "p": p_val, "i": i_val, "d": d_val}
        try:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
            self.show_snackbar(f"Gain change requesting...")
            print(f"Sent gain change: {data}")
        except socket.error as e:
            self.show_snackbar(f"UDP Send Error: {e}")
            self.switch_gain_window(False) 
        
    def gain_save(self):    
        if not hasattr(self, 'dynamicUdpSocket') or not self.dynamicUdpSocket:
            self.show_snackbar("Not connected. Cannot save gain.")
            return
        self.switch_gain_window(True)
        try:
            num_to_send = int(self.selected_actuater) 
            data = {"type":"request_gain_save","num": num_to_send}
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
            self.show_snackbar(f"Gain save requesting...")
            print(f"Sent gain save: {data}")
        except ValueError:
            self.show_snackbar("Invalid actuator ID for gain save.")
            self.switch_gain_window(False)
        except socket.error as e:
            self.show_snackbar(f"UDP Send Error: {e}")
            self.switch_gain_window(False)
        
    def req_capture(self,capture_type_arg): 
        if not hasattr(self, 'dynamicUdpSocket') or not self.dynamicUdpSocket:
            self.show_snackbar("Not connected. Cannot request capture.")
            return
        try:
            num_to_send = int(self.selected_actuater) 
            data = {"type":"request_capture","num": num_to_send, "capture": capture_type_arg}
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
            self.show_snackbar(f"Capture requesting... ⇒  {capture_type_arg}")
            print(f"Sent capture request: {data}")
        except ValueError:
            self.show_snackbar("Invalid actuator ID for capture request.")
        except socket.error as e:
            self.show_snackbar(f"UDP Send Error: {e}")
        
    def switch_actuater(self, num_str_arg, obj): 
        if self.selected_actuater != num_str_arg:
            self.selected_actuater = num_str_arg 
            self.gain_request() 
            self.position_slider.disabled = False
            self.command_slider.disabled = False
            self.offset_capture.disabled = False
            self.stroke_capture.disabled = False
            self.gain_reload.disabled = False
            current_pos = self.position if self.position is not None else 2000
            current_cmd = self.command if self.command is not None else 2000
            self.position_slider.value = current_pos
            self.command_slider.value = current_cmd
            self.slider_position = str(current_pos)
            self.slider_command = str(current_cmd)
            self.before_slider_position = self.slider_position
            self.before_slider_command = self.slider_command
            if hasattr(self, 'update_event') and self.update_event: 
                Clock.unschedule(self.update_event)
                self.update_event = None 
            if hasattr(self.graph_area, 'clear_widgets'):
                self.graph_area.clear_widgets() 
            self.fig = plt.figure() 
            self.fig, self.ax = plt.subplots()
            if self.theme_cls.theme_style == "Dark":
                self.ax.spines['top'].set_color('white')
                self.ax.spines['bottom'].set_color('white')
                self.ax.spines['left'].set_color('white')
                self.ax.spines['right'].set_color('white')
                self.ax.tick_params(axis='y', colors='white')
            self.apply_theme_to_plot() 
            self.x = list(range(200)) 
            self.y1 = [np.nan] * 200 
            self.y2 = [np.nan] * 200
            self.y3 = [np.nan] * 200
            self.y4 = [np.nan] * 200
            self.y5 = [np.nan] * 200
            self.pos_line, = self.ax.plot(self.x, self.y1, label="Position") 
            self.vol_line, = self.ax.plot(self.x, self.y2, label="Voltage")  
            self.com_line, = self.ax.plot(self.x, self.y3, label="Command")  
            self.target_pos_line, = self.ax.plot(self.x, self.y4, label="Target>Position", linestyle='--') 
            self.target_com_line, = self.ax.plot(self.x, self.y5, label="Target>Command", linestyle='--') 
            self.fig.legend() 
            self.ax.set_ylim(0, 4095)
            self.ax.get_xaxis().set_visible(False) 
            if hasattr(self.graph_area, 'add_widget'):
                self.graph_area.add_widget(FigureCanvasKivyAgg(self.fig))   
            self.update_event = Clock.schedule_interval(self.loop_30fps, 1/30.0)
        
    def loop_30fps(self, *args): 
        if not (hasattr(self, 'ax') and self.ax and hasattr(self, 'fig') and self.fig):
            return
        self.y1.append(self.position if self.position_switch.active else np.nan)
        self.y1.pop(0)
        self.y2.append(self.voltage if self.voltage_switch.active else np.nan)
        self.y2.pop(0)
        self.y3.append(self.command if self.command_switch.active else np.nan)
        self.y3.pop(0)
        try: 
            slider_pos_val = int(float(self.slider_position)) 
        except (ValueError, TypeError): 
            slider_pos_val = np.nan 
        self.y4.append(slider_pos_val if self.position_switch.active and self.input_switch.active else np.nan)
        self.y4.pop(0)
        try:
            slider_cmd_val = int(float(self.slider_command)) 
        except (ValueError, TypeError):
            slider_cmd_val = np.nan
        self.y5.append(slider_cmd_val if self.command_switch.active else np.nan) 
        self.y5.pop(0)
        if hasattr(self, 'pos_line'): 
            self.pos_line.set_ydata(self.y1)
            self.vol_line.set_ydata(self.y2)
            self.com_line.set_ydata(self.y3)
            self.target_pos_line.set_ydata(self.y4)
            self.target_com_line.set_ydata(self.y5)
            self.ax.relim()  
            self.ax.autoscale_view() 
            if hasattr(self.fig, 'canvas') and self.fig.canvas:
                self.fig.canvas.draw()
                self.fig.canvas.flush_events()
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            try:
                val_pos_to_send = int(float(self.slider_position))
                val_cmd_to_send = int(float(self.slider_command))
                if self.before_slider_position != self.slider_position:
                    data = {"type":"set_target_value","position":[{"num": str(self.selected_actuater),"value": val_pos_to_send}]}
                    self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
                    print(f"Sent slider position: {data}") 
                    self.before_slider_position = self.slider_position 
                elif self.before_slider_command != self.slider_command: 
                    data = {"type":"set_target_value","command":[{"num": str(self.selected_actuater),"value": val_cmd_to_send}]}
                    self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
                    print(f"Sent slider command: {data}") 
                    self.before_slider_command = self.slider_command
            except (ValueError, TypeError): 
                pass 
            except socket.error as e:
                self.show_snackbar(f"UDP Send Error: {e}")
                
    def update_drawer_menu(self):
        act_num_str = str(self.add_cylinder_num)
        actuator_display_name = self.actuater_name.get(act_num_str, "Other" + str(self.add_cylinder_num - len(self.actuater_name) if self.add_cylinder_num >= len(self.actuater_name) else self.add_cylinder_num))
        if act_num_str not in self._added_actuators_to_drawer: 
            actuater_list_item = MDNavigationDrawerItem(
                MDNavigationDrawerItemText(text=actuator_display_name)
            )
            actuater_list_item.bind(on_release=partial(self.switch_actuater, act_num_str))
            if self.navigation_drawer:
                self.navigation_drawer.add_widget(actuater_list_item)
            self._added_actuators_to_drawer.add(act_num_str) 
        self.add_cylinder_num += 1 
            
    def show_snackbar(self, message_text): 
        if hasattr(self, '_active_snackbar') and self._active_snackbar and self._active_snackbar.get_root_window():
            self._active_snackbar.dismiss()
        self._active_snackbar = MDSnackbar(
            MDSnackbarText(text=message_text),
            pos_hint={"center_x": 0.5, "center_y":0.1},
            size_hint_x=0.8, 
        )
        self._active_snackbar.open()
    
    def apply_theme_to_plot(self): 
        if not hasattr(self, 'ax') or not self.ax or not hasattr(self, 'fig') or not self.fig:
            return 
        is_dark = self.theme_cls.theme_style == "Dark"
        line_color = 'white' if is_dark else 'black'
        plot_face_color = self.theme_cls.surfaceColor 
        fig_face_color = self.theme_cls.backgroundColor 
        self.ax.spines['top'].set_color(line_color)
        self.ax.spines['bottom'].set_color(line_color)
        self.ax.spines['left'].set_color(line_color)
        self.ax.spines['right'].set_color(line_color)
        self.ax.tick_params(axis='y', colors=line_color)
        self.ax.tick_params(axis='x', colors=line_color) 
        self.ax.set_facecolor(plot_face_color) 
        self.fig.set_facecolor(fig_face_color) 
        self.fig.patch.set_alpha(1) 
        self.ax.patch.set_alpha(1)  
        if hasattr(self.fig, 'legend_') and self.fig.legend_: 
            legend = self.fig.legend_
            legend.get_frame().set_facecolor(plot_face_color) 
            legend.get_frame().set_edgecolor(line_color if is_dark else 'grey') 
            for text_item in legend.get_texts(): 
                text_item.set_color(line_color)
        if hasattr(self.fig, 'canvas') and self.fig.canvas: 
            self.fig.canvas.draw_idle()

    def switch_theme_style(self): 
        if self.theme_cls.theme_style == "Light":
            self.theme_cls.theme_style = "Dark"
            if hasattr(self, 'ax'): 
                self.ax.spines['top'].set_color('white')
                self.ax.spines['bottom'].set_color('white')
                self.ax.spines['left'].set_color('white')
                self.ax.spines['right'].set_color('white')
                self.ax.tick_params(axis='y', colors='white')
        else:
            self.theme_cls.theme_style = "Light"
            if hasattr(self, 'ax'):
                self.ax.spines['top'].set_color('black')
                self.ax.spines['bottom'].set_color('black')
                self.ax.spines['left'].set_color('black')
                self.ax.spines['right'].set_color('black')
                self.ax.tick_params(axis='y', colors='black')
        self.apply_theme_to_plot() 
        self.settings_manager.update_setting('theme', self.theme_cls.theme_style)
        self.settings_manager.save_settings() 

    # --- NEW CSV Playback Methods (from previous version, kept for functionality) ---
    def open_csv_file_chooser_dialog(self):
        if not self._file_path_input_dialog:
            self.file_path_input_field = MDTextField(
                hint_text="Enter full path to CSV file",
                text=self.csv_file_path if self.csv_file_path else os.getcwd(), 
                mode="outlined" 
            )
            content_widget = MDBoxLayout( # Renamed from content_cls_box to avoid confusion with content_cls parameter
                orientation='vertical',
                spacing="12dp",
                size_hint_y=None,
                padding="10dp"
            )
            content_widget.bind(minimum_height=content_widget.setter('height'))
            content_widget.add_widget(self.file_path_input_field)

            # Using MDButton with MDButtonText and style="text" for dialog actions
            # This is based on KivyMD 2.0.1 documentation for MDDialog anatomy (p.161)
            cancel_button = MDButton(
                MDButtonText(text="CANCEL"),
                style="text",
                on_release=lambda x: self._file_path_input_dialog.dismiss()
            )
            load_button = MDButton(
                MDButtonText(text="LOAD"),
                style="text",
                on_release=self._process_csv_path_from_dialog
            )
            
            button_container = MDDialogButtonContainer(
                Widget(), # Spacer
                cancel_button,
                load_button,
                spacing="8dp"
            )

            self._file_path_input_dialog = MDDialog(
                MDDialogHeadlineText(text="Load CSV File"), # Set title using MDDialogHeadlineText
                MDDialogContentContainer(content_widget),  # Add content wrapped in its container
                button_container                            # Add button container
            )
        else: 
            self.file_path_input_field.text = self.csv_file_path if self.csv_file_path else os.getcwd()
            # If dialog is reused, ensure its content is up-to-date or reconstruct if necessary.
            # For this case, just updating the text field path might be sufficient.
            
        self._file_path_input_dialog.open()

    def _process_csv_path_from_dialog(self, *args):
        path_str = self.file_path_input_field.text.strip() 
        if os.path.exists(path_str) and path_str.lower().endswith(".csv"):
            self._load_csv_data(path_str)
            if self._file_path_input_dialog: 
                self._file_path_input_dialog.dismiss()
        else:
            self.show_snackbar(f"Invalid file: '{os.path.basename(path_str)}'. Must be an existing .csv file.")

    def _load_csv_data(self, file_path_arg): 
        if not file_path_arg:
            self.show_snackbar("No file path provided.")
            self._reset_csv_state() 
            return
        try:
            temp_data_list = [] 
            with open(file_path_arg, 'r', newline='', encoding='utf-8-sig') as csvfile_obj: 
                reader_obj = csv.reader(csvfile_obj) 
                header_row = next(reader_obj, None) 
                if header_row is None:
                    self.show_snackbar(f"CSV file is empty: {os.path.basename(file_path_arg)}")
                    self._reset_csv_state()
                    return

                expected_columns = 8 
                
                for i_row, row_list in enumerate(reader_obj): 
                    if len(row_list) != expected_columns:
                        self.show_snackbar(f"Row {i_row+2} has {len(row_list)} columns, expected {expected_columns}.")
                        self._reset_csv_state()
                        if hasattr(self, 'loaded_csv_filename_label'): self.loaded_csv_filename_label.text = "Load failed"
                        return 
                    try:
                        temp_data_list.append([int(value_str) for value_str in row_list]) 
                    except ValueError:
                        self.show_snackbar(f"CSV contains non-integer data in row {i_row+2}: {row_list}")
                        self._reset_csv_state()
                        if hasattr(self, 'loaded_csv_filename_label'): self.loaded_csv_filename_label.text = "Parse error"
                        return 
            
            self.csv_data = temp_data_list
            self.csv_file_path = file_path_arg 
            self.loaded_csv_filename = os.path.basename(file_path_arg) 
            if hasattr(self, 'loaded_csv_filename_label'): self.loaded_csv_filename_label.text = self.loaded_csv_filename
            self.settings_manager.update_setting('last_csv_path', self.csv_file_path)
            
            self.play_stop_csv_button.disabled = not bool(self.csv_data) 
            if self.csv_data:
                self.show_snackbar(f"Loaded {len(self.csv_data)} rows from {self.loaded_csv_filename}")
            else: 
                self.show_snackbar(f"No data rows found in {self.loaded_csv_filename}")
            self.current_csv_row_index = 0 
        except FileNotFoundError:
            self.show_snackbar(f"CSV file not found: {file_path_arg}")
            self._reset_csv_state()
        except Exception as e_csv: 
            self.show_snackbar(f"Error loading CSV: {e_csv}")
            self._reset_csv_state()

    def _reset_csv_state(self):
        self.csv_data = []
        self.csv_file_path = ""
        self.loaded_csv_filename = "No CSV loaded"
        if hasattr(self, 'loaded_csv_filename_label'): self.loaded_csv_filename_label.text = self.loaded_csv_filename
        if hasattr(self, 'play_stop_csv_button'): 
            self.play_stop_csv_button.disabled = True
            self.play_stop_csv_button.icon = "play-circle-outline"
        self.is_csv_playing = False


    def toggle_csv_playback(self):
        if not self.csv_data:
            self.show_snackbar("No CSV data loaded. Please load a CSV file first.")
            return

        if not hasattr(self, 'dynamicUdpSocket') or not self.dynamicUdpSocket:
            self.show_snackbar("Not connected to UDP server. Cannot play CSV.")
            return

        self.is_csv_playing = not self.is_csv_playing

        if self.is_csv_playing:
            self.play_stop_csv_button.icon = "stop-circle-outline" 
            csv_stop_event.clear() 
            if self.csv_playback_thread is None or not self.csv_playback_thread.is_alive():
                if self.current_csv_row_index >= len(self.csv_data) and not self.loop_csv: 
                    self.current_csv_row_index = 0 

                self.csv_playback_thread = threading.Thread(target=self.csv_playback_loop)
                self.csv_playback_thread.daemon = True 
                self.csv_playback_thread.start()
        else:
            self.play_stop_csv_button.icon = "play-circle-outline" 
            csv_stop_event.set() 


    def csv_playback_loop(self):
        playback_delay = 1.0 / 30.0  
        
        while self.is_csv_playing and not csv_stop_event.is_set():
            if not self.csv_data: 
                Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())
                break

            if self.current_csv_row_index >= len(self.csv_data):
                if self.loop_csv:
                    self.current_csv_row_index = 0
                else: 
                    Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update(finished=True))
                    break 
            
            if not self.csv_data or self.current_csv_row_index >= len(self.csv_data):
                Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update(finished=not self.loop_csv))
                break

            row_data_list = self.csv_data[self.current_csv_row_index] 
            
            positions_to_send_list = [] 
            for i_actuator, value_actuator in enumerate(row_data_list): 
                positions_to_send_list.append({"num": str(i_actuator), "value": int(value_actuator)}) 

            if positions_to_send_list:
                data_payload_dict = {"type": "set_target_value", "position": positions_to_send_list} 
                try:
                    if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
                        self.dynamicUdpSocket.sendto(json.dumps(data_payload_dict).encode('utf-8'), (self.address, 6060))
                    else: 
                        Clock.schedule_once(lambda dt: self.show_snackbar("UDP connection lost during CSV playback."))
                        Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update()) 
                        break
                except socket.error as e_sock: 
                    print(f"Socket error sending CSV data: {e_sock}")
                    Clock.schedule_once(lambda dt, emsg=str(e_sock): self.show_snackbar(f"UDP Send Error: {emsg}"))
                    Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())
                    break 
                except Exception as e_generic: 
                    print(f"Error sending CSV data: {e_generic}")
                    Clock.schedule_once(lambda dt, emsg=str(e_generic): self.show_snackbar(f"CSV Send Error: {emsg}"))
                    Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())
                    break


            self.current_csv_row_index += 1
            time.sleep(playback_delay) 

        if not self.is_csv_playing and not csv_stop_event.is_set(): 
             Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())


    def _stop_csv_playback_ui_update(self, finished=False):
        self.is_csv_playing = False 
        if hasattr(self, 'play_stop_csv_button'): 
            self.play_stop_csv_button.icon = "play-circle-outline" 
        if finished:
            self.show_snackbar("CSV playback finished.")
            self.current_csv_row_index = 0 
        if hasattr(self, 'play_stop_csv_button'):
            self.play_stop_csv_button.disabled = not bool(self.csv_data)


    def on_loop_csv_changed(self, active_status_bool): 
        self.loop_csv = active_status_bool
        self.settings_manager.update_setting('csv_loop_enabled', self.loop_csv)
        self.show_snackbar(f"Loop CSV: {'Enabled' if self.loop_csv else 'Disabled'}")
    
class SettingsManager: # Using the more robust version from CSV-enabled code
    path = os.path.join(rootdir, 'settings.json')
    def __init__(self, filename=path): 
        self.filename = filename
        self.settings = self.load_settings()

    def load_settings(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as file_obj: 
                settings_dict = json.load(file_obj) 
        except (FileNotFoundError, json.JSONDecodeError) as e_file: 
            print(f"Warning: Settings file error ({e_file}). Using default settings.") 
            settings_dict = { 
                "address": "localhost",
                "theme": "Light",
                "color": "Green",
                "actuater_name": { 
                    "0": "front right hip", "1": "front right knee", "2": "front left hip",
                    "3": "front left knee", "4": "rear right hip", "5": "rear right knee",
                    "6": "rear left hip", "7": "rear left knee"
                },
                "csv_loop_enabled": False, 
                "last_csv_path": "",
                "selected_actuater_default": "0" # Added this for consistency      
            }
        return settings_dict

    def save_settings(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as file_obj: 
                json.dump(self.settings, file_obj, indent=4, ensure_ascii=False) 
        except Exception as e_save: 
            print(f"Error saving settings: {e_save}")

    def update_setting(self, key_str, value_any): 
        self.settings[key_str] = value_any

    def get_setting(self, key_str, default_any=None): 
        return self.settings.get(key_str, default_any)
    
# Restoring NonInteractiveCard and CustomMDButton from older main.py
class NonInteractiveCard(MDCard):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = [10, 10, 10, 10]  # 左、上、右、下の順に余白を設定 (Set padding: left, top, right, bottom)
    def set_properties_widget(self): # This was in older main.py, but not standard KivyMD
        return False
    
class CustomMDButton(MDButton):
    def on_touch_down(self, touch): # This was in older main.py
        if self.disabled:
            return False
        return super().on_touch_down(touch)

if __name__ == '__main__':
    NativeGUIApp().run()
