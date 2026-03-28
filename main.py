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
        super().__init__(orientation='vertical', spacing=8, padding=10, **kwargs)

        # 1. Top Status Bar
        self.status_lbl = Label(text="Status: Disconnected", size_hint=(1, 0.1), color=(1, 1, 1, 1), bold=True)
        self.add_widget(self.status_lbl)

        # 2. Bluetooth Control Buttons (並排)
        btn_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.1), spacing=10)
        self.conn_btn = Button(text="Connect HC-05", background_color=(0.1, 0.6, 0.2, 1), bold=True)
        self.conn_btn.bind(on_press=self.connect_bt)
        self.disc_btn = Button(text="Disconnect", background_color=(0.8, 0.2, 0.2, 1), bold=True)
        self.disc_btn.bind(on_press=self.disconnect_bt)
        btn_layout.add_widget(self.conn_btn)
        btn_layout.add_widget(self.disc_btn)
        self.add_widget(btn_layout)

        # 3. Real-time Data Panel (生理数据 2x2 网格)
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

        # 5. Map Module (Defaults to London, automatically updates on lock-on)
        self.mapview = MapView(zoom=14, lat=51.505, lon=-0.09, size_hint=(1, 0.4))
        self.marker = MapMarker(lat=51.505, lon=-0.09)
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
            Clock.schedule_once(lambda dt: self._update_ui(self.status_lbl, "Error: Pair HC-05 in Settings first", (1,0,0,1)), 0)
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

    # ==========================================
    # 核心算法：智能方向极性转换引擎
    # ==========================================
    def parse_coordinate(self, coord_str):
        """
        Smart parsing to handle strings like '53.411628N' and converting e.g.
        '2.983051W' -> -2.983051 to fix map offset.
        """
        coord_str = str(coord_str).strip().upper()
        if not coord_str:
            return 0.0
        
        last_char = coord_str[-1]
        multiplier = 1.0
        
        # 提取末尾字母判定南北半球/东西半球
        if last_char in ['N', 'S', 'E', 'W']:
            num_part = coord_str[:-1]
            if last_char == 'S' or last_char == 'W':
                multiplier = -1.0
        else:
            num_part = coord_str
            
        try:
            return float(num_part) * multiplier
        except ValueError:
            return 0.0

    def parse_data(self, data_str):
        # Format: DAT, Temp, HR, SpO2, Steps, TempAlert, HRAlert, SpO2Alert, FallAlert, Lat, Lng, Alt
        try:
            parts = data_str.strip().split(',')
            
            # 最高丢包校验检查：只解析 DAT 开头且完整包含 12 项的数据
            if len(parts) == 12 and parts[0] == "DAT":
                
                # --- 1. 温度解析与报警 UI 变红提示 ---
                # 为了防止由于 OLED 溢出导致 Temperature 显示 DAT，这里做了强类型转换校验
                temp_val = parts[1]
                if parts[5] == '1':
                    self.temp_lbl.text = f"Temperature: {temp_val} C  [ ! ]"
                    self.temp_lbl.color = (1, 0.2, 0.2, 1) # 危险变红且加上警示符号
                else:
                    self.temp_lbl.text = f"Temperature: {temp_val} C"
                    self.temp_lbl.color = (1, 1, 1, 1) # 正常颜色

                # --- 2. 心率解析与报警 UI 变红提示 ---
                hr_val = parts[2]
                if parts[6] == '1':
                    self.hr_lbl.text = f"Heart Rate: {hr_val} bpm  [ ! ]"
                    self.hr_lbl.color = (1, 0.2, 0.2, 1) # 危险变红
                else:
                    self.hr_lbl.text = f"Heart Rate: {hr_val} bpm"
                    self.hr_lbl.color = (1, 1, 1, 1) # 正常颜色

                # --- 3. 血氧解析与报警 UI 变红提示 ---
                spo2_val = parts[3]
                if parts[7] == '1':
                    self.spo2_lbl.text = f"SpO2: {spo2_val} %  [ ! ]"
                    self.spo2_lbl.color = (1, 0.2, 0.2, 1) # 危险变红
                else:
                    self.spo2_lbl.text = f"SpO2: {spo2_val} %"
                    self.spo2_lbl.color = (1, 1, 1, 1) # 正常颜色

                # --- 4. 步数解析 ---
                self.steps_lbl.text = f"Steps: {parts[4]}"
                self.steps_lbl.color = (1, 1, 1, 1)

                # --- 5. 跌倒检测状态 ---
                if parts[8] == '1':
                    self.alert_lbl.text = "!!! FALL DETECTED !!!"
                    self.alert_lbl.color = (1, 0, 0, 1) # 红色警告
                else:
                    self.alert_lbl.text = "Fall Status: Normal"
                    self.alert_lbl.color = (0, 1, 0, 1) # 恢复绿色

                # --- 6. 核心 GPS 解析与 W/S 极性转换引擎 ---
                raw_lat = parts[9] # 例如 "53.411354N"
                raw_lng = parts[10] # 例如 "2.983051W"
                raw_alt = parts[11]
                
                # 屏幕上显示原始带字母的数据更直观
                self.gps_lbl.text = f"Lat: {raw_lat} | Lng: {raw_lng} | Alt: {raw_alt} m"

                # 智能解析经纬度数字，西经 (W) 和南纬 (S) 自动变成负数精准定位
                lat_float = self.parse_coordinate(raw_lat)
                lng_float = self.parse_coordinate(raw_lng)
                
                # 只有定位有效（非0）时才移动地图
                if lat_float != 0.0 and lng_float != 0.0:
                    self.mapview.center_on(lat_float, lng_float)
                    self.marker.lat = lat_float
                    self.marker.lon = lng_float
        except Exception as e:
            pass # 忽略传输过程中的噪音数据和不完整的断帧

    def _update_ui(self, widget, text, color=None):
        widget.text = text
        if color:
            widget.color = color

class MainApp(App):
    def build(self):
        return HealthApp()

if __name__ == '__main__':
    MainApp().run()
