from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.utils import platform
from kivy_garden.mapview import MapView, MapMarker
import threading

# 仅在安卓环境下调用 Java 底层经典蓝牙 API
if platform == 'android':
    try:
        from jnius import autoclass
        BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
        UUID = autoclass('java.util.UUID')
    except ImportError:
        BluetoothAdapter = None
        UUID = None
else:
    BluetoothAdapter = None
    UUID = None

class HealthApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=10, padding=10, **kwargs)

        # 1. 顶部状态栏
        self.status_lbl = Label(text="Status: Disconnected", size_hint=(1, 0.1), color=(1, 1, 1, 1), bold=True)
        self.add_widget(self.status_lbl)

        # 2. 蓝牙控制按钮 (并排)
        btn_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.1), spacing=10)
        self.conn_btn = Button(text="Connect HC-05", background_color=(0.1, 0.6, 0.2, 1), bold=True)
        self.conn_btn.bind(on_press=self.connect_bt)
        self.disc_btn = Button(text="Disconnect", background_color=(0.8, 0.2, 0.2, 1), bold=True)
        self.disc_btn.bind(on_press=self.disconnect_bt)
        btn_layout.add_widget(self.conn_btn)
        btn_layout.add_widget(self.disc_btn)
        self.add_widget(btn_layout)

        # 3. 实时数据面板
        grid = GridLayout(cols=2, size_hint=(1, 0.25), spacing=5)
        self.hr_lbl = Label(text="Heart Rate: -- bpm", font_size='18sp')
        self.spo2_lbl = Label(text="SpO2: -- %", font_size='18sp')
        self.temp_lbl = Label(text="Temperature: -- C", font_size='18sp')
        self.steps_lbl = Label(text="Steps: --", font_size='18sp')
        grid.add_widget(self.hr_lbl)
        grid.add_widget(self.spo2_lbl)
        grid.add_widget(self.temp_lbl)
        grid.add_widget(self.steps_lbl)
        self.add_widget(grid)

        # 4. 跌倒警告与 GPS 数值
        self.alert_lbl = Label(text="Fall Status: Normal", size_hint=(1, 0.1), color=(0, 1, 0, 1), bold=True, font_size='20sp')
        self.gps_lbl = Label(text="Lat: -- | Lng: -- | Alt: -- m", size_hint=(1, 0.05))
        self.add_widget(self.alert_lbl)
        self.add_widget(self.gps_lbl)

        # 5. 地图模块 (默认定位北京)
        self.mapview = MapView(zoom=14, lat=39.9042, lon=116.4074, size_hint=(1, 0.4))
        self.marker = MapMarker(lat=39.9042, lon=116.4074)
        self.mapview.add_marker(self.marker)
        self.add_widget(self.mapview)

        # 底层变量
        self.bt_socket = None
        self.input_stream = None
        self.is_connected = False

    def connect_bt(self, instance):
        if platform != 'android':
            self.status_lbl.text = "Please run on Android device"
            return
        if self.is_connected:
            return
        self.status_lbl.text = "Connecting..."
        self.status_lbl.color = (1, 1, 0, 1) # Yellow
        threading.Thread(target=self._bt_thread, daemon=True).start()

    def disconnect_bt(self, instance):
        self.is_connected = False
        try:
            if self.input_stream:
                self.input_stream.close()
            if self.bt_socket:
                self.bt_socket.close()
        except Exception:
            pass
        self._update_ui(self.status_lbl, "Disconnected Successfully", (1, 0.5, 0.5, 1))

    def _bt_thread(self):
        if not BluetoothAdapter or not UUID:
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Error: Bluetooth not available", (1,0,0,1)), 0)
            return

        adapter = BluetoothAdapter.getDefaultAdapter()
        if not adapter or not adapter.isEnabled():
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Error: Please enable Bluetooth", (1,0,0,1)), 0)
            return

        hc05_device = None
        for dev in adapter.getBondedDevices().toArray():
            if dev.getName() == "HC-05":
                hc05_device = dev
                break

        if not hc05_device:
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Error: Pair HC-05 in Phone Settings first", (1,0,0,1)), 0)
            return

        spp_uuid = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
        try:
            self.bt_socket = hc05_device.createRfcommSocketToServiceRecord(spp_uuid)
            adapter.cancelDiscovery()
            self.bt_socket.connect()
            self.input_stream = self.bt_socket.getInputStream()
            self.is_connected = True
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "HC-05 Connected!", (0, 1, 0, 1)), 0)
            self._read_loop()
        except Exception:
            self.is_connected = False
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Connection Failed", (1, 0, 0, 1)), 0)

    def _read_loop(self):
        buffer = ""
        while self.is_connected and self.input_stream:
            try:
                byte_data = self.input_stream.read()
                if byte_data != -1:
                    char_data = chr(byte_data)
                    buffer += char_data
                    if char_data == '\n':
                        # 收到完整一行数据后去解析
                        Clock.schedule_once(lambda dt, b=buffer: self.parse_data(b), 0)
                        buffer = ""
            except Exception:
                self.is_connected = False
                Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Connection Lost", (1, 0, 0, 1)), 0)
                break

    def parse_data(self, data_str):
        # 你的 C 语言发出的格式是: DAT, Temp, HR, SpO2, Steps, 0, 0, 0, 0, 0, FallAlert, Lat, Lng, Alt
        try:
            parts = data_str.strip().split(',')
            
            # 第一项必须是 DAT 才处理，防止乱码
            if len(parts) >= 11 and parts[0] == "DAT":
                # 修复错位：索引 1 是温度，2 是心率，3 是血氧，4 是步数
                self.temp_lbl.text = f"Temperature: {parts[1]} C"
                self.hr_lbl.text = f"Heart Rate: {parts[2]} bpm"
                self.spo2_lbl.text = f"SpO2: {parts[3]} %"
                self.steps_lbl.text = f"Steps: {parts[4]}"

                # 修复跌倒检测：在你的 main.c 里，第11个位置（索引10）是 FallAlert
                if parts[10] == '1':
                    self.alert_lbl.text = "!!! FALL DETECTED !!!"
                    self.alert_lbl.color = (1, 0, 0, 1) # 变红
                else:
                    self.alert_lbl.text = "Fall Status: Normal"
                    self.alert_lbl.color = (0, 1, 0, 1) # 恢复绿色

                # 如果你的 C 语言追加了 GPS 数据 (长度达到 14 项)
                if len(parts) >= 14:
                    lat = float(parts[11])
                    lng = float(parts[12])
                    alt = float(parts[13])
                    
                    self.gps_lbl.text = f"Lat: {lat:.5f} | Lng: {lng:.5f} | Alt: {alt}m"

                    # 只有在搜星成功（非0）时才移动地图
                    if lat != 0.0 and lng != 0.0:
                        self.mapview.center_on(lat, lng)
                        self.marker.lat = lat
                        self.marker.lon = lng
        except Exception as e:
            pass # 忽略传输过程中的断帧错误

    def _update_ui(self, widget, text, color=None):
        widget.text = text
        if color:
            widget.color = color

class MainApp(App):
    def build(self):
        return HealthApp()

if __name__ == '__main__':
    MainApp().run()
