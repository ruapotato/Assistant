# Assistant

Assistant is a modular, AI-powered desktop voice assistant that uses speech recognition and natural language processing to execute commands and interact with your computer.

## Features

- Voice-activated commands
- AI-powered speech recognition using Whisper
- Natural language processing for command interpretation
- Modular architecture for easy extension and customization
- Desktop integration for various actions (typing, speaking, window information)

## Components

1. `trigger-script.py`: Listens for BLE signals to start/stop recording
2. `ear.py`: Handles audio recording based on trigger signals
3. `whisper-server.py`: Transcribes audio using the Whisper model
4. `brain.py`: Processes transcribed commands and executes actions
5. `voice.py`: Converts text to speech using espeak

## Setup

1. Clone the repository:
   ```
   git clone https://github.com/ruapotato/assistant.git
   cd assistant
   ```

2. Create a virtual environment:
   ```
   python3 -m venv pyenv
   ```

3. Activate the virtual environment:
     ```
     source pyenv/bin/activate
     ```

4. Install the required packages:
   ```
   pip install numpy torch transformers sounddevice bleak flask ollama
   pip install 'accelerate>=0.26.0'
   ```

5. Install system dependencies:
   - Install `espeak` for text-to-speech functionality:
     ```
     sudo apt-get install espeak
     ```
   - Install `xdotool` for simulating keyboard input:
     ```
     sudo apt-get install xdotool
     ```
   - Ensure you have the necessary Bluetooth libraries installed for BLE functionality

## Usage

1. Start each component in a separate terminal window:

   ```
   python trigger-script.py
   python ear.py
   python whisper-server.py
   python brain.py
   python voice.py
   ```

2. The system will now listen for voice commands through your configured BLE device.

3. When a command is detected, it will be processed, and the appropriate action will be taken.

4. The assistant will respond verbally using the espeak text-to-speech engine.

## How it works

1. `trigger-script.py` listens for BLE signals and writes "START" or "STOP" to the trigger file.
2. `ear.py` monitors the trigger file, starts/stops recording based on its content, and saves the audio.
3. `whisper-server.py` transcribes the recorded audio using the Whisper model.
4. `brain.py` processes the transcribed commands, interacts with the LLM, and generates responses.
5. `voice.py` monitors the voice directory for new text files, converts them to speech using espeak, and removes processed files.

## Command Flow Process

Here's a detailed breakdown of how a command flows through the system:

1. **Button Press**:
   - A button is pressed on the BLE device.
   - The BLE device sends a signal to start recording.

2. **Trigger Detection**:
   - `trigger-script.py` detects the BLE signal.
   - It writes "START" to the `./trigger` file.

3. **Recording Initiation**:
   - `ear.py` continuously monitors the `./trigger` file.
   - When it sees "START", it begins recording audio.

4. **Audio Capture**:
   - The user speaks a command.
   - `ear.py` captures the audio and saves it as `./audio.raw`.

5. **Recording Termination**:
   - The button is released, sending a stop signal.
   - `trigger-script.py` writes "STOP" to the `./trigger` file.
   - `ear.py` stops recording and writes the path `./audio.raw` to `./whisper_input`.

6. **Speech-to-Text**:
   - `whisper-server.py` monitors the `./whisper_input` file.
   - When a new input is detected, it reads the audio file.
   - It uses the Whisper model to transcribe the audio to text.
   - The transcription is written to the `./heard` file.

7. **Command Processing**:
   - `brain.py` monitors the `./heard` file for new content.
   - When new text appears, it reads and processes the command.
   - It interacts with the LLM to generate an appropriate response.
   - The response is formatted with `<say>` and `<type>` tags as needed.

8. **Action Execution**:
   - `brain.py` executes any actions specified in the response (e.g., typing text).
   - It writes any speech content to a new text file in the `./voice/` directory.

9. **Text-to-Speech**:
   - `voice.py` continuously monitors the `./voice/` directory.
   - When a new text file appears, it reads its content.
   - It uses espeak to convert the text to speech, speaking the response.
   - After speaking, it removes the processed text file.

10. **Cycle Completion**:
    - The system returns to its idle state, ready for the next command.

This process repeats for each new command, allowing for continuous interaction with the assistant.

## Extending the Assistant

To add new functionalities:

1. Modify `brain.py` to include new actions or tools.
2. Update the LLM prompts in `brain.py` to handle new types of commands.
3. If necessary, create new modules and integrate them into the existing architecture.

## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).

Copyright (C) 2024 David Hamner

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
