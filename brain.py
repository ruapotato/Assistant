#!/usr/bin/env python3

import os
import pwd
import json
import requests
import subprocess
import time
from typing import Optional, Dict, List, Union, Tuple

# Constants
MODEL = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
HEARD_FILE = "./heard"
TIMEOUT = 10
DEBUG = True

# Global state
CMD_history: List[str] = []
last_output: str = ""
active_window_id: Optional[str] = None

# System prompts
look_prompt = """You are a Linux Desktop and System Analyzer that gathers context for operations.
Your job is to:
1. Run specific commands to gather context based on the request
2. Return the commands and their expected outputs as structured data

Common scenarios to handle:
- For Active app/window operations:
  * Get window info: "xdotool getactivewindow"
  * Get window content: "import -window $(xdotool getactivewindow) png:- | tesseract stdin stdout"
  * Get window name: "xdotool getwindowname $(xdotool getactivewindow)"
  * Get window geometry: "xdotool getwindowgeometry $(xdotool getactivewindow)"
  * List windows: "wmctrl -l"

- For workspace operations:
  * List workspaces: "wmctrl -d"
  * Get current workspace: "wmctrl -d | grep '*'"

- For screen operations:
  * Get layout: "xrandr --current"
  * Get dimensions: "xdpyinfo | grep dimensions"

- For clipboard/text operations:
  * Get highlighted text: "xclip -o -selection primary"
  * Get clipboard: "xclip -o -selection clipboard"
  * Get file content: "cat [filename]"

Output format must be JSON with:
1. "discovery_commands": Array of commands to gather needed info
2. "purpose": What information we're trying to discover
3. "operation": Type of operation (window, workspace, type, speak, summarize, transcribe)
4. "text": Text to type (for typing operations)

Example outputs:
For "Move active window to desktop 3":
{
    "discovery_commands": [
        "xdotool getactivewindow",
        "wmctrl -d | grep '*'"
    ],
    "purpose": "Getting active window ID and workspace info",
    "operation": "move_to_workspace"
}

For "Summarize clipboard":
{
    "discovery_commands": ["xclip -o -selection clipboard"],
    "purpose": "Getting clipboard content for summarization",
    "operation": "summarize"
}

For "Help me debug this":
{
    "discovery_commands": ["import -window $(xdotool getactivewindow) png:- | tesseract stdin stdout"],
    "purpose": "Read the error in the active app",
    "operation": "speak"
}

For "Type in Hello world":
{
    "discovery_commands": [],
    "purpose": "Typing text directly",
    "operation": "type",
    "text": "Hello world"
}

Must output valid JSON only - no other text."""

act_prompt = """You are a Linux Desktop Controller AI that executes operations.
You receive discovery information and execute the appropriate commands.
Current State:
{state_info}


IMPORTANT: Only output executable commands. No explanation text, no markdown, no backticks.

Common operation types and their format:

For speak operations:
espeak 'your message'
espeak 'command output'  # When reading discovered content

For summarize operations:
espeak "Here's the summary:"
espeak 'First key point'
espeak 'Second key point'

For type operations:
xdotool type "exact text from context"
xdotool key "Return"  # When needed

For window operations:
WINDOW_ID=$(xdotool getactivewindow)
xdotool windowsize $WINDOW_ID width height
xdotool windowmove $WINDOW_ID x y
espeak 'Window operation complete'

For workspace operations:
wmctrl -ir $WINDOW_ID -t workspace_number
espeak 'Moved to workspace'

Rules:
1. Keep espeak messages under 100 characters
2. Use variables for window IDs and dimensions
3. Break long text into multiple espeak commands
4. Quote all variable expansions
5. For type mode, use exact text from context

Example outputs:

For window operation:
WINDOW_ID=$(xdotool getactivewindow)
xdotool windowminimize $WINDOW_ID
espeak 'Window minimized'

For summary:
espeak "Here's what I found:"
espeak "First important point from the text"
espeak "Second key observation"
espeak "Final conclusion"

For typing:
xdotool type "Hello world"
xdotool key "Return"""

def log(msg: str) -> None:
    """Debug logging with timestamp"""
    if DEBUG:
        print(f"\nDEBUG [{time.strftime('%H:%M:%S')}]: {msg}")

def execute_bash(commands: str) -> Tuple[bool, str]:
    """Execute a sequence of bash commands"""
    log(f"Executing bash commands:\n{commands}")
    
    try:
        # Handle espeak commands specially
        if commands.strip().startswith('espeak'):
            cmd = commands.strip()
            # Extract the text to speak
            if '"' in cmd:
                text = cmd.split('"')[1]  # Get text between quotes
            elif "'" in cmd:
                text = cmd.split("'")[1]  # Get text between single quotes
            else:
                text = cmd.replace('espeak', '').strip()
            
            # Execute espeak with cleaned text
            result = subprocess.run(
                ['espeak', text],
                capture_output=True,
                text=True
            )
            time.sleep(0.5)  # Wait for speech to complete
            return result.returncode == 0, ""
            
        # For all other commands
        result = subprocess.run(
            commands,
            shell=True,
            executable='/bin/bash',
            text=True,
            capture_output=True,
            timeout=TIMEOUT
        )
        
        if result.stdout:
            log(f"Command output: {result.stdout.strip()}")
        if result.stderr:
            log(f"Command error: {result.stderr.strip()}")
            
        return result.returncode == 0, result.stdout.strip()
        
    except subprocess.TimeoutExpired:
        log(f"Command timed out after {TIMEOUT}s")
        return False, "Command timed out"
    except Exception as e:
        log(f"Command failed: {str(e)}")
        return False, str(e)

def get_system_state() -> Dict:
    """Gather current system state"""
    state = {
        "windows": [],
        "current_dir": os.getcwd(),
        "last_output": last_output,
        "errors": []
    }
    
    try:
        # Get terminal windows
        result = subprocess.run(
            "xdotool search --class 'gnome-terminal|konsole|xfce4-terminal'",
            shell=True,
            text=True,
            capture_output=True
        )
        
        if result.stdout:
            for window_id in result.stdout.strip().split('\n'):
                try:
                    name = subprocess.run(
                        f"xdotool getwindowname {window_id}",
                        shell=True,
                        text=True,
                        capture_output=True
                    ).stdout.strip()
                    
                    state["windows"].append({
                        "id": window_id,
                        "name": name
                    })
                except:
                    continue
    except Exception as e:
        state["errors"].append(f"Failed to get windows: {str(e)}")
    
    return state

def query_ai(prompt: str, system_prompt: str, context: Optional[List[str]] = None) -> str:
    """Query the AI model"""
    if context is None:
        context = []
        
    log(f"AI Query - Prompt: {prompt[:100]}...")
    
    context_msgs = [{"role": "user", "content": msg} for msg in context]
    context_str = "\n".join([
        f"<|start_header_id|>{msg['role']}<|end_header_id|> {msg['content']}<|eot_id|>"
        for msg in context_msgs
    ])
    
    full_prompt = f"""<|start_header_id|>system<|end_header_id|>{system_prompt}<|eot_id|>
{context_str}
<|start_header_id|>user<|end_header_id|>{prompt}<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>"""

    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                "model": MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "stop": ["<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>"],
                    "num_predict": 8192
                }
            },
            timeout=30
        )
        
        response.raise_for_status()
        return response.json()['response'].strip()
        
    except Exception as e:
        log(f"AI query failed: {str(e)}")
        return ""

def format_context(cmd_history: List[str], last_output: str) -> List[str]:
    """Format command history and output for context"""
    context = []
    
    if cmd_history:
        recent_cmds = "', '".join(cmd_history[-3:])
        context.append(f"Recent commands: '{recent_cmds}'")
    
    if last_output:
        context.append(f"Last output: {last_output}")
        
    return context

def look_and_act(cmd: str) -> str:
    """Analyze environment and execute appropriate actions"""
    global last_output, active_window_id
    
    # Get current system state
    state = get_system_state()
    context = format_context(CMD_history, last_output)
    
    # Look phase - analyze environment
    look_result = query_ai(cmd, look_prompt, context)
    try:
        analysis = json.loads(look_result)
        log(f"Environment analysis: {analysis}")
        
        # Act phase - get commands to execute
        act_context = look_result  # Pass full analysis as context
        commands = query_ai(
            cmd,
            act_prompt.format(state_info=json.dumps(analysis, indent=2)),
            context + [act_context]
        )
        
        if commands:
            # Execute commands
            success, output = execute_bash(commands)
            if success:
                last_output = output
                
                # Update active window if terminal operation
                operation = analysis.get("operation", "")
                if operation in ["terminal", "type"]:
                    try:
                        active_window_id = subprocess.run(
                            "xdotool getactivewindow",
                            shell=True,
                            text=True,
                            capture_output=True
                        ).stdout.strip()
                    except:
                        pass
            else:
                subprocess.run(['espeak', 'Command failed'])
                
            return last_output
            
    except json.JSONDecodeError:
        log("Failed to parse look response")
        subprocess.run(['espeak', 'Failed to analyze environment'])
    except Exception as e:
        log(f"Look and act failed: {str(e)}")
        subprocess.run(['espeak', 'Operation failed'])
        
    return last_output

def process(cmd: str) -> str:
    """Process a user command"""
    global CMD_history
    
    log(f"Processing command: {cmd}")
    CMD_history.append(cmd)
    
    return look_and_act(cmd)

def main():
    """Main loop"""
    log("Starting desktop assistant")
    username = pwd.getpwuid(os.getuid()).pw_name
    
    # Startup greeting
    process(f"Your name is `computer` You are helping '{username}', say hi via espeak.")
    
    while True:
        if os.path.exists(HEARD_FILE):
            try:
                with open(HEARD_FILE, "r") as f:
                    cmd = f.read().strip()
                os.remove(HEARD_FILE)
                
                if cmd:
                    process(cmd)
            except Exception as e:
                log(f"Error processing command: {str(e)}")
                subprocess.run(['espeak', 'Error processing command'])
                
        time.sleep(0.1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
