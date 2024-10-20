import asyncio
from bleak import BleakClient, BleakScanner
import os

TRUSTED_DEVICE = "CIRCUITPY6ef3"
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
TRIGGER_FILE = "./trigger"

def write_trigger_file(content):
    try:
        with open(TRIGGER_FILE, "w") as f:
            f.write(content)
        print(f"Wrote '{content}' to trigger file")
    except Exception as e:
        print(f"Error writing to trigger file: {e}")

def uart_data_handler(sender, data):
    raw_cmd = data.decode().strip()
    print(f"Received command: {raw_cmd}")
    if raw_cmd == "START":
        print("Trigger started...")
        write_trigger_file("START")
    elif raw_cmd == "STOP":
        print("Trigger stopped.")
        write_trigger_file("STOP")

async def run_ble_client(address):
    async with BleakClient(address) as client:
        print(f"Connected: {client.is_connected}")
        await client.start_notify(UART_TX_CHAR_UUID, uart_data_handler)
        print("Notification started")

        while True:
            if not client.is_connected:
                print("Device disconnected")
                break
            await asyncio.sleep(1)

async def main():
    while True:
        try:
            print("Scanning for the trusted device...")
            device = await BleakScanner.find_device_by_name(TRUSTED_DEVICE)
            if device:
                print(f"Found trusted device: {device.name} ({device.address})")
                await run_ble_client(device.address)
            else:
                print(f"Trusted device '{TRUSTED_DEVICE}' not found.")
            
            print("Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            print("Retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
