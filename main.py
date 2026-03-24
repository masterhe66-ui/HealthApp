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
        super().__init__(orientation='vertical', spacing=5, padding=5, **kwargs)

        # 顶部状态栏
        self.status_lbl = Label(text="Status: Disconnected", size_hint=(1, 0.1), color=(1, 0.5, 0.5, 1))
        self.conn_btn = Button(text="Connect HC-05", size_hint=(1, 0.1), background_color=(0, 0.6, 1, 1))
        self.conn_btn.bind(on_press=self.connect_bt)
        self.add_widget(self.status_lbl)
        self.add_widget(self.conn_btn)

        # 数据面板
        grid = GridLayout(cols=2, size_hint=(1, 0.2))
        self.hr_lbl = Label(text="Heart Rate: -- bpm")
        self.spo2_lbl = Label(text="SpO2: -- %")
        self.temp_lbl = Label(text="Temperature: -- C")
        self.steps_lbl = Label(text="Steps: --")
        grid.add_widget(self.hr_lbl)
        grid.add_widget(self.spo2_lbl)
        grid.add_widget(self.temp_lbl)
        grid.add_widget(self.steps_lbl)
        self.add_widget(grid)

        # 跌倒与 GPS 数值
        self.alert_lbl = Label(text="Fall Status: Normal", size_hint=(1, 0.1), color=(0, 1, 0, 1))
        self.gps_lbl = Label(text="Lat: -- | Lng: -- | Alt: -- m", size_hint=(1, 0.1))
        self.add_widget(self.alert_lbl)
        self.add_widget(self.gps_lbl)

        # 地图模块 (默认定位北京)
        self.mapview = MapView(zoom=13, lat=39.9042, lon=116.4074, size_hint=(1, 0.4))
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
        self.status_lbl.text = "Connecting..."
        threading.Thread(target=self._bt_thread, daemon=True).start()

    def _bt_thread(self):
        if not BluetoothAdapter or not UUID:
            Clock.schedule_once(
                lambda dt: self._update_ui(self.status_lbl, "Error: Bluetooth not available on Android"), 0)
            return

        adapter = BluetoothAdapter.getDefaultAdapter()
        if not adapter or not adapter.isEnabled():
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Error: Please enable Bluetooth"), 0)
            return

        hc05_device = None
        for dev in adapter.getBondedDevices().toArray():
            if dev.getName() == "HC-05":
                hc05_device = dev
                break

        if not hc05_device:
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Error: Pair HC-05 first in Settings"), 0)
            return

        spp_uuid = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
        try:
            self.bt_socket = hc05_device.createRfcommSocketToServiceRecord(spp_uuid)
            adapter.cancelDiscovery()
            self.bt_socket.connect()
            self.input_stream = self.bt_socket.getInputStream()
            self.is_connected = True
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "HC-05 Connected!"), 0)
            self._read_loop()
        except Exception:
            self.is_connected = False
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Connection Failed"), 0)

    def _read_loop(self):
        buffer = ""
        while self.is_connected and self.input_stream:
            try:
                byte_data = self.input_stream.read()
                if byte_data != -1:
                    char_data = chr(byte_data)
                    buffer += char_data
                    if char_data == '\n':
                        Clock.schedule_once(lambda dt, b=buffer: self.parse_data(b), 0)
                        buffer = ""
            except Exception:
                self.is_connected = False
                Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Disconnected"), 0)
                break

    def parse_data(self, data_str):
        # 格式: Temp,HR,SpO2,Steps,Fall,Lat,Lng,Alt
        try:
            parts = data_str.strip().split(',')
            if len(parts) >= 8:
                self.temp_lbl.text = f"Temperature: {parts[0]} C"
                self.hr_lbl.text = f"Heart Rate: {parts[1]} bpm"
                self.spo2_lbl.text = f"SpO2: {parts[2]} %"
                self.steps_lbl.text = f"Steps: {parts[3]}"

                if parts[4] == '1':
                    self.alert_lbl.text = "!!! FALL DETECTED !!!"
                    self.alert_lbl.color = (1, 0, 0, 1)
                else:
                    self.alert_lbl.text = "Fall Status: Normal"
                    self.alert_lbl.color = (0, 1, 0, 1)

                lat, lng, alt = float(parts[5]), float(parts[6]), float(parts[7])
                self.gps_lbl.text = f"Lat: {lat:.5f} | Lng: {lng:.5f} | Alt: {alt}m"

                if lat != 0.0 and lng != 0.0:
                    self.mapview.center_on(lat, lng)
                    self.marker.lat = lat
                    self.marker.lon = lng
        except Exception:
            pass

    def _update_ui(self, widget, text):
        widget.text = text


class MainApp(App):
    def build(self):
        return HealthApp()


if __name__ == '__main__':
    MainApp().run()
