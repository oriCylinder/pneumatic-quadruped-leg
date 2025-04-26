import os

# GUIライブラリのインポート
from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.config import Config
from kivy.core.window import Window
Config.set('graphics', 'maxfps', 60)

# GUIコンポーネント関連
from kivymd.uix.card import MDCard
from kivymd.uix.button import MDButton
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.navigationdrawer import MDNavigationDrawerItem, MDNavigationDrawerItemText

# Kivyフォント関連
from kivy.core.text import LabelBase, DEFAULT_FONT
fontdir = os.path.join(os.path.dirname(__file__), 'font', 'NotoSansJP-Regular.ttf')
rootdir = os.path.dirname(__file__)
LabelBase.register(DEFAULT_FONT, fontdir)

# グラフ描画関連
import numpy as np
from kivy.clock import Clock
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg
import matplotlib
matplotlib.use('Agg')   #非アクティブになる現象を抑止
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont(fontdir) #matplotlib
plt.rc('font', family="Noto Sans JP")

# 画面遷移関連
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from functools import partial

# 通信関連
import json
import socket
import threading
import time

stop_event = threading.Event()

class StartScreen(MDScreen):
    def on_connect_button_press(self):
        """接続ボタンが押されたときに通信を開始します。"""
        app = MDApp.get_running_app()
        app.start_communication()

class MainScreen(MDScreen):
    def on_disconnect_button_press(self):
        """切断ボタンが押されたときに通信を切断します。"""
        app = MDApp.get_running_app()
        app.stop_communication("Disconnected!")

class PageManager(MDScreenManager):
    pass
    
class NativeGUIApp(MDApp):
    Builder.load_file(os.path.join(rootdir, 'layout.kv'))
    trans_data =  ''
    selected_actuater = 0
    add_cylinder_num = 0
    
    def build(self):    #描画が始まる前の処理
        self.screen_manager = PageManager()
        self.settings_manager = SettingsManager()
        
        #System Component
        self.theme_cls.theme_style_switch_animation = True
        self.theme_cls.theme_style = self.settings_manager.get_setting('theme')
        self.theme_cls.primary_palette = self.settings_manager.get_setting('color')
        self.actuater_name = self.settings_manager.get_setting('actuater_name')
        
        #Start Screen Component
        self.screen_manager.get_screen('start').ids.address_field.text = self.settings_manager.get_setting('address')
        self.connect_button = self.screen_manager.get_screen('start').ids.connect_button
        self.address_field = self.screen_manager.get_screen('start').ids.address_field
        self.progressindicator = self.screen_manager.get_screen('start').ids.progressindicator
        
        #Main Screen Component
        self.graph_area = self.screen_manager.get_screen('main').ids.graph_area
        self.input_switch = self.screen_manager.get_screen('main').ids.input_switch
        self.position_switch = self.screen_manager.get_screen('main').ids.position_switch
        self.voltage_switch = self.screen_manager.get_screen('main').ids.voltage_switch
        self.command_switch = self.screen_manager.get_screen('main').ids.command_switch
        self.navigation_drawer = self.screen_manager.get_screen('main').ids.nav_drawer_menu

        # Main Screen Locked Component
        self.gain_reload = self.screen_manager.get_screen('main').ids.gain_reload
        self.p_field = self.screen_manager.get_screen('main').ids.gain_p
        self.i_field = self.screen_manager.get_screen('main').ids.gain_i
        self.d_field = self.screen_manager.get_screen('main').ids.gain_d
        self.gain_send = self.screen_manager.get_screen('main').ids.gain_send
        self.save_button = self.screen_manager.get_screen('main').ids.gain_save
        self.position_slider = self.screen_manager.get_screen('main').ids.position_slider
        self.command_slider = self.screen_manager.get_screen('main').ids.command_slider
        self.offset_capture = self.screen_manager.get_screen('main').ids.offset_capture
        self.stroke_capture = self.screen_manager.get_screen('main').ids.stroke_capture
        
        self.udp_thread = None        
        return self.screen_manager
    
    def on_start(self): #描画が始まったときの処理
        Window.maximize()
        self.screen_manager.get_screen('main').ids.nav_drawer.set_state("open")
        self.fig = plt.figure()
        self.fig, self.ax = plt.subplots()
        
    
    def on_stop(self):  #描画が止まるときの処理
        stop_event.set()
        return True
    
    def start_communication(self):
        """UDP通信を開始（スレッド）"""
        address_field = self.screen_manager.get_screen('start').ids.address_field
        self.address = address_field.text
        
        #送り側のソケットを定義
        self.dynamicUdpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.udp_thread = None
        stop_event.clear()

        if not self.udp_thread:
            self.udp_thread = threading.Thread(target=self.udp_receiver, args=(self.address,))
            self.udp_thread.start()

    def stop_communication(self, message):
        """UDPの通信を切断します。"""
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
        
        if hasattr(self, 'update_event'):
            Clock.unschedule(self.update_event)
        
        self.navigation_drawer.children[0].clear_widgets() #ドロワーを初期化
        self.graph_area.clear_widgets() #グラフを初期化
        self.selected_actuater = 0
        self.add_cylinder_num = 0
        
        stop_event.set()
        Clock.schedule_once(lambda dt: self.show_snackbar(message)) # エラーメッセージをsnackbarに表示
    
    def udp_receiver(self,address):
        self.settings_manager.update_setting('address', self.screen_manager.get_screen('start').ids.address_field.text)
        self.settings_manager.save_settings()
        self.connect_button.disabled = True
        self.address_field.disabled = True
        self.progressindicator.active = True
        
        print("UDPサーバーに接続中")
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.settimeout(3)
            self.udp_socket.bind(("0.0.0.0", 6050))
            print("UDPでサーバーからのメッセージを受信中...")
            
            #初回のデータを受け取ったときの処理 PVCが送られて来るまで待ち
            while not stop_event.is_set():
                data, addr = self.udp_socket.recvfrom(4096)
                receive_data = data.decode()
                self.trans_data = json.loads(receive_data)
                if self.trans_data['type'] == "current_sensor_value":
                    break
                
            print(f"Connected: {addr}")
            #PVCデータを受け取ったら画面遷移
            Clock.schedule_once(lambda x: self.change_screen('main'))

            current_num = 0
                
            #データの取得と変数への格納
            while not stop_event.is_set():
                try:              
                    data, addr = self.udp_socket.recvfrom(4096)
                except TimeoutError:
                    time.sleep(0.1)
                    continue
                receive_data = data.decode()
                self.trans_data = json.loads(receive_data)
                if self.trans_data['type'] == "current_sensor_value":
                    cylinder_num = self.trans_data["sensors"][0]["num"]
                    if cylinder_num == current_num:
                        Clock.schedule_once(lambda dt: self.update_drawer_menu())
                        current_num += 1
                    if cylinder_num == int(self.selected_actuater):
                        self.position = next((sensor['position'] for sensor in self.trans_data.get('sensors', []) if sensor.get('num') == int(self.selected_actuater)), None)
                        self.voltage = next((sensor['voltage'] for sensor in self.trans_data.get('sensors', []) if sensor.get('num') == int(self.selected_actuater)), None)
                        self.command = next((sensor['command'] for sensor in self.trans_data.get('sensors', []) if sensor.get('num') == int(self.selected_actuater)), None)
                elif self.trans_data['type'] == "response_gain_value":
                    cylinder_num = str(self.trans_data["num"])
                    if cylinder_num == self.selected_actuater:
                        self.p = self.trans_data.get("gains", {}).get("p", None)
                        self.i = self.trans_data.get("gains", {}).get("i", None)
                        self.d = self.trans_data.get("gains", {}).get("d", None)
                        self.capture_max = self.trans_data.get("capture", {}).get("max", None)
                        self.capture_min = self.trans_data.get("capture", {}).get("min", None)
                        Clock.schedule_once(lambda x: self.gain_sync(self.p,self.i,self.d))
                
            self.udp_socket.close()
            self.udp_socket = None
            print("切断しました")

        except Exception as e:
            error_message = f"UDP Communication Error: {e}"
            print(error_message)
            Clock.schedule_once(lambda x: self.stop_communication(error_message))

    def change_screen(self, screen_name):
        self.root.current = screen_name
    
    def switch_gain_window(self, switch):
        self.p_field.disabled = switch
        self.i_field.disabled = switch
        self.d_field.disabled = switch
        self.gain_send.disabled = switch
        self.save_button.disabled = switch
        
    def gain_request(self):     #4.1
        self.switch_gain_window(True)
        data = {"type": "request_gain_value", "num": self.selected_actuater}
        self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
        print(data)
        
    def gain_sync(self,p,i,d): #1.4/4.4/5.4/6.4/7.4
        self.p_field.text = str(p)
        self.i_field.text = str(i)
        self.d_field.text = str(d)
        self.switch_gain_window(False)
        
    def fixed_motion(self,motion):     #4.1
        data = {"type": "fixed_motion", "motion": motion}
        self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
        self.show_snackbar(f"Fixed motion requesting... ⇒ {motion}")
        print(data)
        

    def gain_change(self):    #7.1
        #self.switch_gain_window(True) #入力を禁止します
        gain_values = {"p": self.p_field.text, "i": self.i_field.text, "d": self.d_field.text}
        self.switch_gain_window(True)
        data = {"type": "set_gain_value", "num": int(self.selected_actuater), "p": gain_values.get("p"), "i": gain_values.get("i"), "d": gain_values.get("d")}
        self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address, 6060))
        self.show_snackbar(f"Gain change requesting...")
        print(data)

        
    def gain_save(self):    #5.1
        self.switch_gain_window(True)
        data = {"type":"request_gain_save","num":self.selected_actuater}
        self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
        self.show_snackbar(f"Gain save requesting...")
        print(data)
        
    def req_capture(self,capture_type):  #6.1
        data = {"type":"request_capture","num":self.selected_actuater, "capture": capture_type}
        self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
        self.show_snackbar(f"Capture requesting... ⇒  {capture_type}")
        print(data)
        
    def switch_actuater(self, num, obj):
        """アクチュエータを変更・選択したとき"""
        if self.selected_actuater != num:
            self.selected_actuater = num
            self.gain_request()
            self.position_slider.disabled = False
            self.command_slider.disabled = False
            self.offset_capture.disabled = False
            self.stroke_capture.disabled = False
            self.gain_reload.disabled = False
            position = self.position
            command = self.command
            self.screen_manager.get_screen('main').ids.position_slider.value = position
            self.screen_manager.get_screen('main').ids.command_slider.value = command
            self.before_slider_position = position
            self.before_slider_command = command
            self.slider_position = position
            self.slider_command = command
            
            if hasattr(self, 'update_event'):
                Clock.unschedule(self.update_event)
                
            self.graph_area.clear_widgets() #グラフを初期化
            
            self.fig = plt.figure()
            self.fig, self.ax = plt.subplots()
            if self.theme_cls.theme_style == "Dark":
                self.ax.spines['top'].set_color('white')
                self.ax.spines['bottom'].set_color('white')
                self.ax.spines['left'].set_color('white')
                self.ax.spines['right'].set_color('white')
                self.ax.tick_params(axis='y', colors='white')
            
            self.fig.patch.set_alpha(0)
            self.ax.patch.set_alpha(0)
            
            self.x = list(range(200))
            self.y1 = [0] * 200
            self.y2 = [0] * 200
            self.y3 = [0] * 200
            self.y4 = [0] * 200
            self.y5 = [0] * 200
            
            self.pos_line, = self.ax.plot(self.x, self.y1, label="Position")  # 1本目の線
            self.vol_line, = self.ax.plot(self.x, self.y2, label="Voltage")  # 2本目の線
            self.com_line, = self.ax.plot(self.x, self.y3, label="Command")  # 3本目の線
            self.target_pos_line, = self.ax.plot(self.x, self.y4, label="Target>Position")  # 4本目の線
            self.target_com_line, = self.ax.plot(self.x, self.y5, label="Target>Command")  # 5本目の線
            
            self.fig.legend()
            self.ax.set_ylim(0, 4095)
            
            self.ax.get_xaxis().set_visible(False)
            
            self.graph_area.add_widget(FigureCanvasKivyAgg(self.fig))   #新規グラフを追加
            self.update_event = Clock.schedule_interval(self.loop_30fps, 1/30)
        
    def loop_30fps(self, *args):
        """グラフの更新"""
        # 1本目の線のy値の更新
        self.y1.append(self.position) if self.position_switch.active == True else self.y1.append(None) # y1値の更新
        self.y1.pop(0)  # 古いy1値の削除

        # 2本目の線のy値の更新
        self.y2.append(self.voltage) if self.voltage_switch.active == True else self.y2.append(None) # y2値の更新
        self.y2.pop(0)  # 古いy2値の削除
        
        # 3本目の線のy値の更新
        self.y3.append(self.command) if self.command_switch.active == True else self.y3.append(None) # y3値の更新
        self.y3.pop(0)  # 古いy3値の削除
        
        # 4本目の線のy値の更新
        self.y4.append(int(self.slider_position)) if self.position_switch.active == True & self.input_switch.active == True else self.y4.append(None) # y4値の更新
        self.y4.pop(0)  # 古いy4値の削除
        
        # 5本目の線のy値の更新
        self.y5.append(int(self.slider_command)) if self.command_switch.active == True else self.y5.append(None) # y5値の更新
        self.y5.pop(0)  # 古いy5値の削除

        # 各線のデータを更新
        self.pos_line.set_ydata(self.y1)
        self.vol_line.set_ydata(self.y2)
        self.com_line.set_ydata(self.y3)
        self.target_pos_line.set_ydata(self.y4)
        self.target_com_line.set_ydata(self.y5)

        self.ax.relim()  # limitsを再計算
        self.ax.autoscale_view()  # スケールを更新

        self.fig.canvas.draw()
        self.fig.canvas.flush_events()
        
        """Target送信"""
        if self.before_slider_position != self.slider_position:
            data = {"type":"set_target_value","position":[{"num":self.selected_actuater,"value":self.slider_position}]}
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
            print(data)
        elif self.before_slider_command != self.slider_command:
            data = {"type":"set_target_value","command":[{"num":self.selected_actuater,"value":self.slider_command}]}
            self.dynamicUdpSocket.sendto(json.dumps(data).encode('utf-8'), (self.address,6060))
            print(data)
        self.before_slider_position = self.slider_position
        self.before_slider_command = self.slider_command
                
    def update_drawer_menu(self):
        actuater_list = MDNavigationDrawerItem(
            MDNavigationDrawerItemText(text=self.actuater_name.get(str(self.add_cylinder_num), "Other" + str(self.add_cylinder_num - len(self.actuater_name)))))
        actuater_list.bind(on_release=partial(self.switch_actuater, str(self.add_cylinder_num)))
        self.navigation_drawer.add_widget(actuater_list)
        self.add_cylinder_num += 1
            
    def show_snackbar(self, message):
        snackbar = MDSnackbar(
            MDSnackbarText(
                text=message,
            ),
            pos_hint={"center_x": 0.5, "center_y":0.1},
            size_hint_x=0.5,
        )
        snackbar.open()
    
    def switch_theme_style(self):
        if self.theme_cls.theme_style == "Light":
            self.theme_cls.theme_style = "Dark"
            self.ax.spines['top'].set_color('white')
            self.ax.spines['bottom'].set_color('white')
            self.ax.spines['left'].set_color('white')
            self.ax.spines['right'].set_color('white')
            self.ax.tick_params(axis='y', colors='white')
        else:
            self.theme_cls.theme_style = "Light"
            self.ax.spines['top'].set_color('black')
            self.ax.spines['bottom'].set_color('black')
            self.ax.spines['left'].set_color('black')
            self.ax.spines['right'].set_color('black')
            self.ax.tick_params(axis='y', colors='black')
            
        self.settings_manager.update_setting('theme', self.theme_cls.theme_style)
        self.settings_manager.save_settings()
    
class SettingsManager:
    path = os.path.join(rootdir, 'settings.json')
    def __init__(self, filename=path):
        self.filename = filename
        self.settings = self.load_settings()

    def load_settings(self):
        """設定をJSONファイルから読み込みます。ファイルが存在しない場合は空の設定を返します。"""
        try:
            with open(self.filename, 'r') as file:
                settings = json.load(file)
        except FileNotFoundError:
            settings = {}  # デフォルト設定を定義
        return settings

    def save_settings(self):
        """現在の設定をJSONファイルに保存します。"""
        with open(self.filename, 'w') as file:
            json.dump(self.settings, file, indent=4)

    def update_setting(self, key, value):
        """設定を更新します。"""
        self.settings[key] = value

    def get_setting(self, key, default=None):
        """設定を取得します。指定されたキーが存在しない場合はデフォルト値を返します。"""
        return self.settings.get(key, default)
    
class NonInteractiveCard(MDCard):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.padding = [10, 10, 10, 10]  # 左、上、右、下の順に余白を設定
    def set_properties_widget(self):
        return False
    
class CustomMDButton(MDButton):
    def on_touch_down(self, touch):
        if self.disabled:
            return False
        return super().on_touch_down(touch)

if __name__ == '__main__':
    NativeGUIApp().run()