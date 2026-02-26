import serial
import threading
import time
import re
import collections
import matplotlib
import matplotlib.pyplot as plt
import sys
import statistics as st
import os
import json

# Configuration
DEFAULT_PORT = 'COM5'  # e.g. 'COM3' or '/dev/ttyACM0'; leave None to be prompted
BAUDRATE = 9600      # Must match Serial.begin(...) in Arduino
BUFFER_SIZE = 300    # number of points to keep in the plot
CALIBRATION_FILE = 'calibration.json'
NUM_SENSORS= 6

# Load or initialize calibration parameters
def load_calibration():
    """Load calibration parameters from file if it exists."""
    if os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, 'r') as f:
                data = json.load(f)
                offsets = data.get('offset', [None] * 6)
                scales = data.get('facteurEchelle', [None] * 6)
                known_wt = data.get('known_weight', None)
                # Ensure we have arrays for all 6 sensors
                if not isinstance(offsets, list):
                    offsets = [offsets] * 6
                if not isinstance(scales, list):
                    scales = [scales] * 6
                return offsets[:6], scales[:6], known_wt
        except Exception as e:
            print(f"Error loading calibration file: {e}")
    return [None] * 6, [None] * 6, None

# Initialize calibration parameters
offsets, facteurEchelles, known_weight = load_calibration()
if all(o is not None for o in offsets):
    print(f"Loaded calibration for all 6 sensors")
    for i, (off, scale) in enumerate(zip(offsets, facteurEchelles)):
        print(f"  Sensor {i + 1}: Offset={off}, Scale Factor={scale}")
else:
    print("No complete calibration file found. A new calibration will be created.")

# Serial port selection logic
if DEFAULT_PORT is not None :
    port = DEFAULT_PORT
else:
    port = input('Enter serial port (e.g. COM3 or /dev/ttyACM0): ').strip()

if not port:
    print('No serial port provided. Exiting.')
    sys.exit(1)

# Open serial port
try:
    ser = serial.Serial(port, BAUDRATE, timeout=1)
    time.sleep(2)  # allow Arduino to reset
except Exception as e:
    print(f'Failed to open serial port {port}: {e}')
    sys.exit(1)

print('If you have not already, please complete the calibration steps on the Arduino (follow serial monitor instructions) before running this script.')
print('Waiting for numeric data from Arduino...')

# Calibration process
calibration = 'n'  # Default: don't perform calibration
if any(o is None for o in offsets):
    calibration = input('Do you want to perform calibration ? (y/n): ')
if calibration == 'y' or calibration == 'Y':
    # Calibration parameters
    CALIBRATION_SAMPLES = 10

    def get_median_raw(sensor_index=0, samples=CALIBRATION_SAMPLES):
        """Get median raw value for a specific sensor."""
        vals = []
        print(f"Collecting {samples} raw samples from sensor {sensor_index + 1}...")
        for i in range(20):
            test=ser.readline()  
            print(test)
        while len(vals) < samples:
            raw = ser.readline()
            try:
                line = raw.decode('utf-8', errors='ignore').strip()
                values = line.split(',')
                if len(values) > sensor_index:
                    val = int(values[sensor_index].strip())
                    print(f"Sensor {sensor_index + 1}: {val}")
                    vals.append(val)
            except:
                continue
        med=st.median(vals)
        print(f"Median raw value (Sensor {sensor_index + 1}): {med}")
        return med

    print("\n--- CALIBRATION ---")
    print("You will calibrate each sensor individually.")
    print("Make sure all sensors have the same load when taring and when placing known weight.")
    
    for sensor_idx in range(NUM_SENSORS):
        print(f"\n--- Calibrating Sensor {sensor_idx + 1} ---")
        input(f"1. Remove all weight from sensor {sensor_idx + 1} and press Enter to tare...")
        ser.reset_input_buffer()
        offsets[sensor_idx] = get_median_raw(sensor_idx)
        print(f"Tare complete. Offset = {offsets[sensor_idx]}")

        input(f"2. Place a known weight on sensor {sensor_idx + 1} and press Enter...")
        known_weight_sensor = None
        while known_weight_sensor is None:
            try:
                known_weight_sensor = float(input(f"Enter the known weight in g (for sensor {sensor_idx + 1}): "))
                if known_weight_sensor <= 0:
                    known_weight_sensor = None
                    print("Please enter a positive value in grams.")
            except:
                print("Invalid input. Try again.")

        ser.reset_input_buffer()
        raw_with_weight = get_median_raw(sensor_idx)
        print(f"Raw value with weight: {raw_with_weight}")
        
        if raw_with_weight == offsets[sensor_idx]:
            print(f"Error: No difference between tare and loaded value for sensor {sensor_idx + 1}. Check your hardware.")
            facteurEchelles[sensor_idx] = 1  # Default fallback
        else:
            facteurEchelles[sensor_idx] = (raw_with_weight - offsets[sensor_idx]) / known_weight_sensor
            print(f"Calibration complete. Scale factor (Sensor {sensor_idx + 1}) = {facteurEchelles[sensor_idx]} (raw units per gram)")
            if abs(facteurEchelles[sensor_idx]) < 0.01:
                print(f"Warning: Scale factor for sensor {sensor_idx + 1} is very small. Calibration may be incorrect.")
    
    print("\n--- END CALIBRATION ---\n")
    save_choice = input("Do you want to save calibration parameters ? (y/n): ").strip().lower()
    if save_choice == 'y':
        try:
            with open(CALIBRATION_FILE, 'w') as f:
                json.dump({
                    'offset': offsets,
                    'facteurEchelle': facteurEchelles,
                    'known_weight': known_weight
                }, f, indent=4)
            print(f"Calibration parameters saved to {CALIBRATION_FILE}")
        except Exception as e:
            print(f"Error saving calibration file: {e}")

# Shared state
NUM_SENSORS = 6
data = [collections.deque(maxlen=BUFFER_SIZE) for _ in range(NUM_SENSORS)]  # stores floats for each sensor
index = collections.deque(maxlen=BUFFER_SIZE) # x axis (shared)
_lock = threading.Lock()
_running = True
first_data_received = threading.Event()


def reader_thread():
    i = 0
    global _running
    while _running:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            try:
                # Parse comma-separated values for all 6 sensors
                values = line.split(',')
                if len(values) != NUM_SENSORS:
                    continue
                
                raw_values = [int(v.strip()) for v in values]
                
                with _lock:
                    all_valid = True
                    weights = []
                    
                    # Convert raw values to weights for all sensors
                    for sensor_idx in range(NUM_SENSORS):
                        if offsets[sensor_idx] is not None and facteurEchelles[sensor_idx] is not None:
                            poids_g = (raw_values[sensor_idx] - offsets[sensor_idx]) / facteurEchelles[sensor_idx]
                            if poids_g > -50:
                                weights.append(poids_g)
                            else:
                                all_valid = False
                                break
                        else:
                            weights.append(raw_values[sensor_idx])  # Store raw value if not calibrated
                    
                    # If all sensors are valid, add to data
                    if all_valid:
                        for sensor_idx in range(NUM_SENSORS):
                            data[sensor_idx].append(weights[sensor_idx])
                        index.append(i)
                        
                        print(f"Sample {i}: {', '.join([f'S{j+1}: {w:.1f}g' for j, w in enumerate(weights)])}")
                        first_data_received.set()
                i += 1
            except Exception as e:
                print(f"Parse error: {e}")
                continue
        except Exception:
            continue


# Start reader thread
t = threading.Thread(target=reader_thread, daemon=True)
t.start()

# Wait for first valid data (i.e., after calibration)
first_data_received.wait()
print('Numeric data received. Plotting started. Press Ctrl+C to stop.')

# Setup matplotlib figure
plt.style.use('seaborn-darkgrid')
fig, ax = plt.subplots(figsize=(12, 6))

plt.ion()  # Turn on interactive mode

# Record start time for runtime display
start_time = time.time()

try:
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown']
    while _running:
        # Clear previous plot
        ax.clear()
        
        with _lock:
            if len(index) == 0:
                time.sleep(0.01)
                continue
            x = list(index)
        
        
        # Plot weight from all sensors
        for sensor_idx in range(NUM_SENSORS):
            with _lock:
                y = list(data[sensor_idx])
            if len(y) > 0:
                ax.plot(x, y, color=colors[sensor_idx], linewidth=2, label=f'Sensor {sensor_idx + 1}')
        
        # Set labels and title
        ax.set_title('Real-time Arduino Weight Measurement - All Sensors')
        ax.set_xlabel('Sample')
        ax.set_ylabel('Weight (g)')
        
        # Update axes limits dynamically
        if len(x) > 0:
            ax.set_xlim(max(0, x[0]), x[-1] + 1)
            
            # Find min and max across all sensors
            all_values = []
            for sensor_idx in range(NUM_SENSORS):
                with _lock:
                    all_values.extend(list(data[sensor_idx]))
            
            if all_values:
                ymin = min(0, min(all_values))
                ymax = max(all_values)
                if ymin == ymax:
                    ymax += 10
                ax.set_ylim(ymin, ymax + 0.1 * abs(ymax or 1))
        
        # Add grid and legend
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Set a common title with running time
        current_time = time.time()
        elapsed_time = current_time - start_time
        elapsed_minutes = int(elapsed_time // 60)
        elapsed_seconds = int(elapsed_time % 60)
        fig.suptitle(f"Runtime: {elapsed_minutes}m {elapsed_seconds}s | Samples: {len(x)}")

        # Update display
        plt.tight_layout()
        plt.pause(1)  # Update display every 1s
        
except KeyboardInterrupt:
    print("Stopping plot...")

# Shutdown
_running = False
try:
    t.join(timeout=1)
except:
    pass
try:
    ser.close()
except:
    pass
print('Stopped.')