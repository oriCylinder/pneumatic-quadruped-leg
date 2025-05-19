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
from kivymd.uix.button import MDButton, MDIconButton, MDButtonText
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.navigationdrawer import MDNavigationDrawerItem, MDNavigationDrawerItemText
from kivymd.uix.dialog import MDDialog, MDDialogHeadlineText, MDDialogContentContainer, MDDialogButtonContainer
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
    selected_actuater = NumericProperty(0) # 旧版に合わせてNumericPropertyに変更
    add_cylinder_num = 0 
    
    # CSV Playback Properties (remains for now)
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
        self.theme_cls.theme_style = self.settings_manager.get_setting('theme', 'Light') # default value
        self.theme_cls.primary_palette = self.settings_manager.get_setting('color', 'Green') # default value
        self.actuater_name = self.settings_manager.get_setting('actuater_name', {}) # default value
        # selected_actuater は NumericProperty なので、設定から読み込む際は適切に変換
        try:
            self.selected_actuater = int(self.settings_manager.get_setting('selected_actuater_default', '0'))
        except ValueError:
            self.selected_actuater = 0


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
        self.input_switch = main_screen_ids.input_switch # CSV機能で使う可能性があるので残す
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
        # self._added_actuators_to_drawer = set() # 旧版のロジックでは不要
        return self.screen_manager
    
    def on_start(self): 
        Window.maximize()
        self.screen_manager.get_screen('main').ids.nav_drawer.set_state("open")
        self.fig, self.ax = plt.subplots()
        # apply_theme_to_plot() は旧版にはないので、テーマ適用はswitch_actuater等で行う

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
        
        # 旧版のドロワークリア方法 (main (1).py L109)
        # MDNavigationDrawerMenu の最初の子供 (通常はMDNavigationDrawerContent) のウィジェットをクリア
        if self.navigation_drawer and self.navigation_drawer.children:
            # self.navigation_drawer.children[0] がアイテムを保持するコンテナであることを想定
            # より安全なのは self.navigation_drawer.clear_widgets() だが、旧版に合わせる
            try:
                if hasattr(self.navigation_drawer.children[0], 'clear_widgets'):
                     self.navigation_drawer.children[0].clear_widgets()
                elif isinstance(self.navigation_drawer.children[0], list) and len(self.navigation_drawer.children[0]) > 0:
                    # This case might be specific to how items were added if children[0] is a list of items
                    # For now, let's assume clear_widgets on the container is preferred.
                    # If it's a direct list of items, this part might need more specific handling.
                    pass # Or try self.navigation_drawer.clear_widgets() as a fallback
            except IndexError:
                # Fallback if children[0] doesn't exist as expected
                self.navigation_drawer.clear_widgets()


        if hasattr(self.graph_area, 'clear_widgets'): 
            self.graph_area.clear_widgets() 
        
        self.selected_actuater = 0 # 旧版に合わせてリセット
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
        # self.settings_manager.save_settings() # 旧版では接続時に毎回保存はしていない
        Clock.schedule_once(lambda dt: setattr(self.connect_button, 'disabled', True))
        Clock.schedule_once(lambda dt: setattr(self.address_field, 'disabled', True))
        Clock.schedule_once(lambda dt: setattr(self.progressindicator, 'active', True))
        print("UDPサーバーに接続中")
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.settimeout(3.0) # 旧版と同じタイムアウト
            self.udp_socket.bind(("0.0.0.0", 6050))
            print("UDPでサーバーからのメッセージを受信中...")
            
            # 初回データ受信 (旧版 main (1).py L124-130)
            initial_data_received_flag = False
            while not stop_event.is_set():
                try:
                    data, addr = self.udp_socket.recvfrom(4096)
                    receive_data = data.decode('utf-8', errors='ignore') # 旧版は decode() のみだが、エラー処理追加
                    self.trans_data = json.loads(receive_data)
                    if self.trans_data.get('type') == "current_sensor_value":
                        initial_data_received_flag = True
                        break 
                except socket.timeout:
                    print("Waiting for initial data from server (timeout)...") # タイムアウト時のメッセージ
                    if stop_event.is_set(): break
                    continue
                except json.JSONDecodeError as je:
                    print(f"JSON Decode Error (initial): {je} - Data: '{receive_data}'")
                    # 旧版ではここでループを抜けてしまう可能性があるが、エラーを出して続ける方が良い場合も
                except Exception as e: 
                    print(f"Error during initial data reception: {e}")
                    Clock.schedule_once(lambda x, err_msg=str(e): self.stop_communication(f"Connection Error: {err_msg}"))
                    return # スレッドを終了

            if not initial_data_received_flag and not stop_event.is_set(): # 接続失敗
                Clock.schedule_once(lambda x: self.stop_communication("Failed to receive initial sensor data."))
                return

            if not stop_event.is_set(): # 接続成功時
                print(f"Connected: {addr}")
                Clock.schedule_once(lambda x: self.change_screen('main'))

            current_num_for_drawer = 0 # 旧版の current_num (ドロワー更新用)
                
            while not stop_event.is_set():
                try:              
                    data, addr = self.udp_socket.recvfrom(4096)
                except socket.timeout: # 旧版は TimeoutError だが、socket.timeout がより一般的
                    # time.sleep(0.1) # 旧版の挙動
                    if stop_event.is_set(): break # 停止イベントをチェック
                    continue
                except Exception as e: 
                    if not stop_event.is_set():
                        print(f"UDP recv error during operation: {e}")
                    break 
                
                receive_data = data.decode('utf-8', errors='ignore') # 旧版は decode()
                try:
                    self.trans_data = json.loads(receive_data)
                except json.JSONDecodeError as je:
                    print(f"JSON Decode Error (loop): {je} - Data: '{receive_data}'")
                    continue 
                
                msg_type = self.trans_data.get('type')
                if msg_type == "current_sensor_value":
                    sensors_data = self.trans_data.get("sensors", [])
                    if sensors_data:
                        # ドロワー更新 (旧版 main (1).py L140-143)
                        first_sensor_num = sensors_data[0].get("num") # 最初のセンサーの番号を取得
                        if first_sensor_num is not None and first_sensor_num == current_num_for_drawer:
                            Clock.schedule_once(lambda dt: self.update_drawer_menu())
                            current_num_for_drawer += 1
                        
                        # センサーデータ更新 (旧版 main (1).py L144-147)
                        # self.selected_actuater は NumericProperty (int)
                        self.position = next((s.get('position') for s in sensors_data if s.get('num') == self.selected_actuater), self.position)
                        self.voltage = next((s.get('voltage') for s in sensors_data if s.get('num') == self.selected_actuater), self.voltage)
                        self.command = next((s.get('command') for s in sensors_data if s.get('num') == self.selected_actuater), self.command)

                elif msg_type == "response_gain_value":
                    # 旧版 main (1).py L148-154
                    cylinder_num_from_json = self.trans_data.get("num")
                    # selected_actuater は int なので、比較のために型を合わせる
                    if str(cylinder_num_from_json) == str(self.selected_actuater): 
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
            print("切断しました (UDP receiver stopped)") # 旧版は「切断しました」
        except Exception as e: # 旧版 main (1).py L160-163
            error_message = f"UDP Communication Error: {e}" # 旧版のエラーメッセージ形式
            print(error_message)
            if not stop_event.is_set(): # stop_eventがセットされていなければUI更新
                 Clock.schedule_once(lambda x, emsg=error_message: self.stop_communication(emsg))
        finally: # finallyブロックは現行版の方が良いが、旧版にはない
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
        
    def gain_request(self):     # 旧版 main (1).py L173
        self.switch_gain_window(True)
        # self.selected_actuater は NumericProperty (int)
        data = {"type": "request_gain_value", "num": self.selected_actuater}
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
            print(f"Sent gain request: {data}") # print内容は現行版の方が詳細
        else:
            self.show_snackbar("Not connected for gain request.")


    def gain_sync(self,p_val,i_val,d_val): # 旧版 main (1).py L178
        self.p_field.text = str(p_val if p_val is not None else "") # Noneチェック追加
        self.i_field.text = str(i_val if i_val is not None else "") # Noneチェック追加
        self.d_field.text = str(d_val if d_val is not None else "") # Noneチェック追加
        self.switch_gain_window(False)
        
    def fixed_motion(self,motion_type): # 旧版 main (1).py L184   
        data = {"type": "fixed_motion", "motion": motion_type}
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
            self.show_snackbar(f"Fixed motion requesting... ⇒ {motion_type}")
            print(f"Sent fixed motion: {data}")
        else:
            self.show_snackbar("Not connected for fixed motion.")
        
    def gain_change(self):    # 旧版 main (1).py L192
        try:
            p_val = float(self.p_field.text)
            i_val = float(self.i_field.text)
            d_val = float(self.d_field.text)
        except ValueError:
            self.show_snackbar("Invalid gain values.")
            return
        self.switch_gain_window(True)
        # self.selected_actuater は NumericProperty (int)
        data = {"type": "set_gain_value", "num": self.selected_actuater, "p": p_val, "i": i_val, "d": d_val}
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
            self.show_snackbar(f"Gain change requesting...")
            print(f"Sent gain change: {data}")
        else:
            self.show_snackbar("Not connected for gain change.")
            self.switch_gain_window(False) 
        
    def gain_save(self):    # 旧版 main (1).py L202
        self.switch_gain_window(True)
        # self.selected_actuater は NumericProperty (int)
        data = {"type":"request_gain_save","num":self.selected_actuater}
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
            self.show_snackbar(f"Gain save requesting...")
            print(f"Sent gain save: {data}")
        else:
            self.show_snackbar("Not connected for gain save.")
            self.switch_gain_window(False)
        
    def req_capture(self,capture_type_arg): # 旧版 main (1).py L209
        # self.selected_actuater は NumericProperty (int)
        data = {"type":"request_capture","num":self.selected_actuater, "capture": capture_type_arg}
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
            self.show_snackbar(f"Capture requesting... ⇒  {capture_type_arg}")
            print(f"Sent capture request: {data}")
        else:
            self.show_snackbar("Not connected for capture request.")

    def switch_actuater(self, num_str_arg, obj): # num_str_arg は文字列で渡ってくる
        try:
            num_to_switch = int(num_str_arg)
        except ValueError:
            print(f"Invalid actuator number string: {num_str_arg}")
            return

        # 旧版 main (1).py L215 の条件分岐
        # if self.selected_actuater != num_str_arg: # 旧版は文字列比較だったが、型を合わせる
        if self.selected_actuater != num_to_switch:
            self.selected_actuater = num_to_switch 
            self.settings_manager.update_setting('selected_actuater_default', str(self.selected_actuater)) # 設定保存時は文字列
            self.gain_request() 
            
            self.position_slider.disabled = False
            self.command_slider.disabled = False
            self.offset_capture.disabled = False
            self.stroke_capture.disabled = False
            self.gain_reload.disabled = False
            
            # スライダーの値更新 (旧版 main (1).py L221-226)
            current_pos = self.position if self.position is not None else 2000
            current_cmd = self.command if self.command is not None else 2000
            
            self.screen_manager.get_screen('main').ids.position_slider.value = current_pos
            self.screen_manager.get_screen('main').ids.command_slider.value = current_cmd
            
            # slider_position/command (StringProperty) も更新
            self.slider_position = str(current_pos)
            self.slider_command = str(current_cmd)
            self.before_slider_position = self.slider_position 
            self.before_slider_command = self.slider_command
            
            if hasattr(self, 'update_event') and self.update_event: 
                Clock.unschedule(self.update_event)
                self.update_event = None # 明示的にNoneに設定
            if hasattr(self.graph_area, 'clear_widgets'):
                self.graph_area.clear_widgets() 
            
            # self.fig = plt.figure() # 旧版 main (1).py L230
            self.fig, self.ax = plt.subplots() # 旧版 main (1).py L231

            # テーマ適用 (旧版 main (1).py L232-237)
            if self.theme_cls.theme_style == "Dark":
                self.ax.spines['top'].set_color('white')
                self.ax.spines['bottom'].set_color('white')
                self.ax.spines['left'].set_color('white')
                self.ax.spines['right'].set_color('white')
                self.ax.tick_params(axis='y', colors='white')
                self.ax.tick_params(axis='x', colors='white') # X軸もテーマ適用
            else: # Light theme
                self.ax.spines['top'].set_color('black')
                self.ax.spines['bottom'].set_color('black')
                self.ax.spines['left'].set_color('black')
                self.ax.spines['right'].set_color('black')
                self.ax.tick_params(axis='y', colors='black')
                self.ax.tick_params(axis='x', colors='black') # X軸もテーマ適用

            # 透明度設定 (旧版 main (1).py L239-240)
            self.fig.patch.set_alpha(0)
            self.ax.patch.set_alpha(0)
            
            self.x = list(range(200)) 
            # yデータ初期化 (np.nan を使用してデータがない部分は描画しない)
            self.y1 = [np.nan] * 200 
            self.y2 = [np.nan] * 200
            self.y3 = [np.nan] * 200
            self.y4 = [np.nan] * 200 # 旧版は [0]*200
            self.y5 = [np.nan] * 200 # 旧版は [0]*200
            
            self.pos_line, = self.ax.plot(self.x, self.y1, label="Position") 
            self.vol_line, = self.ax.plot(self.x, self.y2, label="Voltage")  
            self.com_line, = self.ax.plot(self.x, self.y3, label="Command")  
            # 旧版 main (1).py L250-251 のラベルと linestyle
            self.target_pos_line, = self.ax.plot(self.x, self.y4, label="Target>Position", linestyle='--') 
            self.target_com_line, = self.ax.plot(self.x, self.y5, label="Target>Command", linestyle='--') 
            
            self.fig.legend() # 旧版 main (1).py L253
            
            self.ax.set_ylim(0, 4095) # Y軸の範囲を固定
            self.ax.get_xaxis().set_visible(False) 
            
            if hasattr(self.graph_area, 'add_widget'):
                self.graph_area.add_widget(FigureCanvasKivyAgg(self.fig))   
            
            self.update_event = Clock.schedule_interval(self.loop_30fps, 1/30.0) # 旧版は 1/30
        # else: # アクチュエータが変更されなかった場合 (初回選択問題の可能性)
            # ここで強制的にグラフ描画処理を呼び出すか検討。
            # ただし、「元に戻す」という指示なので、旧版のロジックを優先。
            # 初回描画問題は、接続完了時に一度 switch_actuater を呼ぶなどで対応する方が良い。
            # 例えば on_connect_button_press の成功時や udp_receiver で画面遷移後に
            # Clock.schedule_once(lambda dt: self.switch_actuater(str(self.selected_actuater), None))

        
    def loop_30fps(self, *args): # 旧版 main (1).py L260
        if not (hasattr(self, 'ax') and self.ax and hasattr(self, 'fig') and self.fig):
            return

        # グラフデータ更新 (旧版 main (1).py L262-276)
        self.y1.append(self.position if self.position_switch.active else np.nan)
        self.y1.pop(0)
        self.y2.append(self.voltage if self.voltage_switch.active else np.nan)
        self.y2.pop(0)
        self.y3.append(self.command if self.command_switch.active else np.nan)
        self.y3.pop(0)
        
        try:
            slider_pos_val = int(float(self.slider_position))
        except (ValueError, TypeError):
            slider_pos_val = np.nan # 旧版はエラーになるが、nanで描画しない方が安全
        # 旧版は self.input_switch の考慮なし
        self.y4.append(slider_pos_val if self.position_switch.active and self.input_switch.active else np.nan)
        self.y4.pop(0)
        
        try:
            slider_cmd_val = int(float(self.slider_command))
        except (ValueError, TypeError):
            slider_cmd_val = np.nan # 旧版はエラーになるが、nanで描画しない方が安全
        self.y5.append(slider_cmd_val if self.command_switch.active else np.nan)
        self.y5.pop(0)

        if hasattr(self, 'pos_line') and self.pos_line.axes: 
            self.pos_line.set_ydata(self.y1)
            self.vol_line.set_ydata(self.y2)
            self.com_line.set_ydata(self.y3)
            self.target_pos_line.set_ydata(self.y4)
            self.target_com_line.set_ydata(self.y5)

            self.ax.relim()  
            self.ax.autoscale_view()  

            if hasattr(self.fig, 'canvas') and self.fig.canvas:
                try:
                    self.fig.canvas.draw()
                    self.fig.canvas.flush_events()
                except Exception as e:
                    print(f"Error during canvas draw: {e}") 
        
        # ターゲット送信 (旧版 main (1).py L286-294)
        # self.selected_actuater は int, self.slider_position/command は StringProperty
        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket: # dynamicUdpSocket の存在確認
            try:
                if self.before_slider_position != self.slider_position:
                    data = {"type":"set_target_value","position":[{"num":str(self.selected_actuater),"value":self.slider_position}]}
                    self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
                    # print(f"Sent slider position: {data}") # 旧版は print(data)
                    self.before_slider_position = self.slider_position 
                elif self.before_slider_command != self.slider_command: 
                    data = {"type":"set_target_value","command":[{"num":str(self.selected_actuater),"value":self.slider_command}]}
                    self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
                    # print(f"Sent slider command: {data}") # 旧版は print(data)
                    self.before_slider_command = self.slider_command
            except socket.error as e:
                self.show_snackbar(f"UDP Send Error: {e}")
            except Exception as e: # その他のエラー
                print(f"Error sending target value: {e}")

    def update_drawer_menu(self): # 旧版 main (1).py L296
        # self.add_cylinder_num は int
        # self.actuater_name は辞書で、キーは文字列のはず
        actuator_display_name = self.actuater_name.get(str(self.add_cylinder_num), "Other" + str(self.add_cylinder_num - len(self.actuater_name) if self.add_cylinder_num >= len(self.actuater_name) else self.add_cylinder_num))
        
        actuater_list_item = MDNavigationDrawerItem(
            MDNavigationDrawerItemText(text=actuator_display_name)
        )
        # switch_actuater には文字列でアクチュエータ番号を渡す
        actuater_list_item.bind(on_release=partial(self.switch_actuater, str(self.add_cylinder_num)))
        
        if self.navigation_drawer:
            self.navigation_drawer.add_widget(actuater_list_item)
        self.add_cylinder_num += 1
            
    def show_snackbar(self, message_text): # 旧版 main (1).py L303 のスタイルに合わせる
        snackbar = MDSnackbar(
            MDSnackbarText(
                text=message_text,
            ),
            pos_hint={"center_x": 0.5, "center_y":0.1},
            size_hint_x=0.5, # 旧版のサイズ
        )
        snackbar.open()
    
    def switch_theme_style(self): # 旧版 main (1).py L314
        if self.theme_cls.theme_style == "Light":
            self.theme_cls.theme_style = "Dark"
            if hasattr(self, 'ax'): 
                self.ax.spines['top'].set_color('white')
                self.ax.spines['bottom'].set_color('white')
                self.ax.spines['left'].set_color('white')
                self.ax.spines['right'].set_color('white')
                self.ax.tick_params(axis='y', colors='white')
                self.ax.tick_params(axis='x', colors='white') # X軸も
        else:
            self.theme_cls.theme_style = "Light"
            if hasattr(self, 'ax'):
                self.ax.spines['top'].set_color('black')
                self.ax.spines['bottom'].set_color('black')
                self.ax.spines['left'].set_color('black')
                self.ax.spines['right'].set_color('black')
                self.ax.tick_params(axis='y', colors='black')
                self.ax.tick_params(axis='x', colors='black') # X軸も
        
        # apply_theme_to_plot() は呼ばない (旧版の挙動)
        # グラフの再描画が必要な場合は draw_idle を呼ぶ
        if hasattr(self, 'fig') and hasattr(self.fig, 'canvas') and self.fig.canvas:
            self.fig.canvas.draw_idle()

        self.settings_manager.update_setting('theme', self.theme_cls.theme_style)
        self.settings_manager.save_settings()
    
    # --- CSV Playback Methods (Kept from current version) ---
    def open_csv_file_chooser_dialog(self):
        if not self._file_path_input_dialog:
            self.file_path_input_field = MDTextField(
                hint_text="Enter full path to CSV file",
                text=self.csv_file_path if self.csv_file_path else os.getcwd(), 
                mode="outlined" 
            )
            content_widget = MDBoxLayout( 
                orientation='vertical',
                spacing="12dp",
                size_hint_y=None,
                padding="10dp"
            )
            content_widget.bind(minimum_height=content_widget.setter('height'))
            content_widget.add_widget(self.file_path_input_field)

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
                Widget(), 
                cancel_button,
                load_button,
                spacing="8dp"
            )

            self._file_path_input_dialog = MDDialog(
                MDDialogHeadlineText(text="Load CSV File"), 
                MDDialogContentContainer(content_widget),  
                button_container                            
            )
        else: 
            self.file_path_input_field.text = self.csv_file_path if self.csv_file_path else os.getcwd()
            
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
                    
                    processed_row = []
                    for value_str in row_list:
                        if value_str.strip() == "": 
                            processed_row.append("")
                        else:
                            try:
                                processed_row.append(int(value_str)) 
                            except ValueError:
                                self.show_snackbar(f"CSV contains non-integer data in row {i_row+2}: {value_str}")
                                self._reset_csv_state()
                                if hasattr(self, 'loaded_csv_filename_label'): self.loaded_csv_filename_label.text = "Parse error"
                                return
                    temp_data_list.append(processed_row)
            
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
        if hasattr(self, 'position_slider'):
            self.position_slider.disabled = False
        if hasattr(self, 'command_slider'):
            self.command_slider.disabled = False


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
            self.position_slider.disabled = True
            self.command_slider.disabled = True
            csv_stop_event.clear() 
            if self.csv_playback_thread is None or not self.csv_playback_thread.is_alive():
                if self.current_csv_row_index >= len(self.csv_data) and not self.loop_csv: 
                    self.current_csv_row_index = 0 

                self.csv_playback_thread = threading.Thread(target=self.csv_playback_loop)
                self.csv_playback_thread.daemon = True 
                self.csv_playback_thread.start()
        else:
            self.play_stop_csv_button.icon = "play-circle-outline" 
            self.position_slider.disabled = False
            self.command_slider.disabled = False
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
            
            for i_actuator, value_actuator in enumerate(row_data_list):
                if value_actuator != "": # 値が空文字列でなければ送信処理
                    # CSVの値をスライダーに同期 (選択中のアクチュエータのみ)
                    if str(i_actuator) == str(self.selected_actuater): # selected_actuater は int なので str() で比較
                        Clock.schedule_once(lambda dt, val=value_actuator: setattr(self, 'slider_position', str(val)))


                    data_payload_dict = {
                        "type": "set_target_value",
                        "position": [{"num": str(i_actuator), "value": int(value_actuator)}]
                    }
                    try:
                        if hasattr(self, 'dynamicUdpSocket') and self.dynamicUdpSocket:
                            self.dynamicUdpSocket.sendto(json.dumps(data_payload_dict).encode('utf-8'), (self.address, 6060))
                        else: 
                            Clock.schedule_once(lambda dt: self.show_snackbar("UDP connection lost during CSV playback."))
                            Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update()) 
                            break 
                    except socket.error as e_sock: 
                        print(f"Socket error sending CSV data for actuator {i_actuator}: {e_sock}")
                        Clock.schedule_once(lambda dt, emsg=str(e_sock): self.show_snackbar(f"UDP Send Error: {emsg}"))
                        Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())
                        break 
                    except Exception as e_generic: 
                        print(f"Error sending CSV data for actuator {i_actuator}: {e_generic}")
                        Clock.schedule_once(lambda dt, emsg=str(e_generic): self.show_snackbar(f"CSV Send Error: {emsg}"))
                        Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())
                        break
            
            if not self.is_csv_playing or csv_stop_event.is_set(): 
                break

            self.current_csv_row_index += 1
            time.sleep(playback_delay) 

        if not self.is_csv_playing and not csv_stop_event.is_set(): 
             Clock.schedule_once(lambda dt: self._stop_csv_playback_ui_update())


    def _stop_csv_playback_ui_update(self, finished=False):
        self.is_csv_playing = False 
        if hasattr(self, 'play_stop_csv_button'): 
            self.play_stop_csv_button.icon = "play-circle-outline" 
        if hasattr(self, 'position_slider'):
            self.position_slider.disabled = False
        if hasattr(self, 'command_slider'):
            self.command_slider.disabled = False

        if finished:
            self.show_snackbar("CSV playback finished.")
            self.current_csv_row_index = 0 
        if hasattr(self, 'play_stop_csv_button'):
            self.play_stop_csv_button.disabled = not bool(self.csv_data)


    def on_loop_csv_changed(self, active_status_bool): 
        self.loop_csv = active_status_bool
        self.settings_manager.update_setting('csv_loop_enabled', self.loop_csv)
        self.show_snackbar(f"Loop CSV: {'Enabled' if self.loop_csv else 'Disabled'}")
    
class SettingsManager: 
    path = os.path.join(rootdir, 'settings.json')
    def __init__(self, filename=path): 
        self.filename = filename
        self.settings = self.load_settings()

    def load_settings(self): # 旧版 main (1).py L334
        try:
            with open(self.filename, 'r', encoding='utf-8') as file_obj: # encoding='utf-8' を追加
                settings_dict = json.load(file_obj) 
        except FileNotFoundError: 
            # 旧版は {} を返すが、より具体的なデフォルト設定を持つ方が望ましい場合もある
            print("Warning: Settings file not found. Using default settings.") 
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
                "selected_actuater_default": "0"      
            }
        except json.JSONDecodeError: # JSONデコードエラーも考慮
            print("Warning: Settings file is corrupted. Using default settings.")
            settings_dict = { # 同上のデフォルト設定
                "address": "localhost", "theme": "Light", "color": "Green",
                "actuater_name": {"0": "frh", "1": "frk"}, # 短縮例
                "csv_loop_enabled": False, "last_csv_path": "", "selected_actuater_default": "0"
            }
        return settings_dict

    def save_settings(self): # 旧版 main (1).py L341
        try:
            with open(self.filename, 'w', encoding='utf-8') as file_obj: # encoding='utf-8' を追加
                json.dump(self.settings, file_obj, indent=4, ensure_ascii=False) # ensure_ascii=False を追加
        except Exception as e_save: 
            print(f"Error saving settings: {e_save}")

    def update_setting(self, key_str, value_any): # 旧版 main (1).py L345 (引数名変更)
        self.settings[key_str] = value_any

    def get_setting(self, key_str, default=None): # 旧版 main (1).py L349 (引数名変更)
        return self.settings.get(key_str, default)
    
class NonInteractiveCard(MDCard):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = [10, 10, 10, 10]  
    def set_properties_widget(self): 
        return False
    
class CustomMDButton(MDButton):
    def on_touch_down(self, touch): 
        if self.disabled:
            return False
        return super().on_touch_down(touch)

if __name__ == '__main__':
    NativeGUIApp().run()
