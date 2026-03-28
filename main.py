from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.utils import platform
from kivy_garden.mapview import MapView, MapMarker
import threading

# Use Java Bluetooth API only on Android
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

        # 1. Top Status Bar
        self.status_lbl = Label(text="Status: Disconnected", size_hint=(1, 0.1), color=(1, 1, 1, 1), bold=True)
        self.add_widget(self.status_lbl)

        # 2. Bluetooth Control Buttons
        btn_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.1), spacing=10)
        self.conn_btn = Button(text="Connect HC-05", background_color=(0.1, 0.6, 0.2, 1), bold=True)
        self.conn_btn.bind(on_press=self.connect_bt)
        self.disc_btn = Button(text="Disconnect", background_color=(0.8, 0.2, 0.2, 1), bold=True)
        self.disc_btn.bind(on_press=self.disconnect_bt)
        btn_layout.add_widget(self.conn_btn)
        btn_layout.add_widget(self.disc_btn)
        self.add_widget(btn_layout)

        # 3. Real-time Data Panel
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

        # 4. Fall Alert & GPS Coordinates Display
        self.alert_lbl = Label(text="Fall Status: Normal", size_hint=(1, 0.1), color=(0, 1, 0, 1), bold=True, font_size='20sp')
        self.gps_lbl = Label(text="Lat: -- | Lng: -- | Alt: -- m", size_hint=(1, 0.05))
        self.add_widget(self.alert_lbl)
        self.add_widget(self.gps_lbl)

        # 5. Map Module (Default location set to 53.4116, -2.9846)
        self.mapview = MapView(zoom=14, lat=53.4116, lon=-2.9846, size_hint=(1, 0.4))
        self.marker = MapMarker(lat=53.4116, lon=-2.9846)
        self.mapview.add_marker(self.marker)
        self.add_widget(self.mapview)

        # Underlying Variables
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
                        Clock.schedule_once(lambda dt, b=buffer: self.parse_data(b), 0)
                        buffer = ""
            except Exception:
                self.is_connected = False
                Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Connection Lost", (1, 0, 0, 1)), 0)
                break

    # ==========================================
    # 核心算法：智能转换 N/S/E/W 到正负数
    # ==========================================
    def parse_coordinate(self, coord_str):
        """
        Converts strings like '53.411628N' -> 53.411628
        and '2.984626W' -> -2.984626 for map accuracy.
        """
        coord_str = str(coord_str).strip().upper()
        if not coord_str:
            return 0.0
        
        last_char = coord_str[-1]
        multiplier = 1.0
        
        # If string ends with N, S, E, W
        if last_char in ['N', 'S', 'E', 'W']:
            num_part = coord_str[:-1]
            # South and West are negative coordinates
            if last_char == 'S' or last_char == 'W':
                multiplier = -1.0
        else:
            num_part = coord_str # Fallback if it's already a regular number
            
        try:
            return float(num_part) * multiplier
        except ValueError:
            return 0.0

    def parse_data(self, data_str):
        # Format: DAT, Temp, HR, SpO2, Steps, [flags], FallAlert, Lat, Lng, Alt
        try:
            parts = data_str.strip().split(',')
            
            if len(parts) >= 11 and parts[0] == "DAT":
                self.temp_lbl.text = f"Temperature: {parts[1]} C"
                self.hr_lbl.text = f"Heart Rate: {parts[2]} bpm"
                self.spo2_lbl.text = f"SpO2: {parts[3]} %"
                self.steps_lbl.text = f"Steps: {parts[4]}"

                # Index 10 is Fall Alert based on your C code
                if parts[10] == '1':
                    self.alert_lbl.text = "!!! FALL DETECTED !!!"
                    self.alert_lbl.color = (1, 0, 0, 1) # Red
                else:
                    self.alert_lbl.text = "Fall Status: Normal"
                    self.alert_lbl.color = (0, 1, 0, 1) # Green

                if len(parts) >= 14:
                    raw_lat = parts[11] # Might be "53.411628N"
                    raw_lng = parts[12] # Might be "2.984626W"
                    raw_alt = parts[13]
                    
                    # 使用智能解析器转换为浮点数
                    lat_float = self.parse_coordinate(raw_lat)
                    lng_float = self.parse_coordinate(raw_lng)
                    
                    # 屏幕上显示原始带字母的数据更直观
                    self.gps_lbl.text = f"Lat: {raw_lat} | Lng: {raw_lng} | Alt: {raw_alt} m"

                    # 地图使用带有正负号的精准数据进行移动
                    if lat_float != 0.0 and lng_float != 0.0:
                        self.mapview.center_on(lat_float, lng_float)
                        self.marker.lat = lat_float
                        self.marker.lon = lng_float
        except Exception as e:
            pass 

    def _update_ui(self, widget, text, color=None):
        widget.text = text
        if color:
            widget.color = color

class MainApp(App):
    def build(self):
        return HealthApp()

if __name__ == '__main__':
    MainApp().run()
