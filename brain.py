import os
import pwd
import json
import requests
import re
import subprocess
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='desktop_controller.log'
)

username = pwd.getpwuid(os.getuid()).pw_name
heard_file = "./heard"
voice_dir = "./voice"
MODEL = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
YOLO = True
CMD_history = []
last_from_ai = ""

import os
import pwd
import json
import requests
import re
import subprocess
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='desktop_controller.log'
)

username = pwd.getpwuid(os.getuid()).pw_name
heard_file = "./heard"
voice_dir = "./voice"
MODEL = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
YOLO = True
CMD_history = []
last_from_ai = ""

evaluate_prompt = """You are a Linux Desktop and System Analyzer that gathers context for operations.
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

For "What do you think about this?":
{
    "discovery_commands": [
        "import -window $(xdotool getactivewindow) png:- | tesseract stdin stdout",
        "xclip -o -selection clipboard"
    ],
    "purpose": "Pull in data the user might be talking about",
    "operation": "speak"
}

Must output valid JSON only - no other text."""

execute_prompt = """You are a Linux Desktop Controller AI that executes operations.
You receive discovery information and execute the appropriate commands.

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
xdotool key "Return"

Never include explanatory text or markdown formatting - only executable commands."""

def execute_command(command):
    """Execute a command and return its output"""
    print(f"┌─[assistant]─[{time.strftime('%H:%M:%S')}]\n└──╼ {command}")
    logging.info(f"Executing command: {command}")
    try:
        # For espeak commands, execute without capturing output
        if command.startswith('espeak'):
            result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.5)  # Increased delay for better speech spacing
            if result.returncode != 0:
                print(f"Error: {result.stderr.decode()}")
                logging.error(f"Espeak command failed: {result.stderr.decode()}")
            return ""
            
        # For piped commands, use a different approach
        elif '|' in command:
            result = subprocess.run(command, shell=True, text=True, capture_output=True)
            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    print(output)
                return output
            else:
                error_msg = f"Error: {result.stderr}"
                print(error_msg)
                logging.error(error_msg)
                return error_msg
            
        # For all other commands
        else:
            result = subprocess.run(
                command,
                shell=True,
                text=True,
                capture_output=True,
                timeout=5
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output:
                    print(output)
                logging.info(f"Command succeeded with output: {output}")
                return output
            else:
                error_msg = f"Error: {result.stderr}"
                print(error_msg)
                logging.error(error_msg)
                return error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out: {command}"
        print(error_msg)
        logging.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Error executing command: {str(e)}"
        print(error_msg)
        logging.error(error_msg)
        return error_msg

def process_commands(text):
    """Process commands from AI response"""
    logging.info(f"Processing commands: {text}")
    
    # Split commands while preserving quoted strings
    commands = []
    current_command = []
    in_quotes = False
    quote_char = None
    
    for char in text:
        if char in "\"'":
            if not in_quotes:
                in_quotes = True
                quote_char = char
            elif quote_char == char:
                in_quotes = False
                quote_char = None
        elif char in ";\n" and not in_quotes:
            current_command.append(char)
            commands.append(''.join(current_command).strip())
            current_command = []
            continue
        current_command.append(char)
    
    if current_command:
        commands.append(''.join(current_command).strip())
    
    # Execute each command and store window ID for subsequent commands
    results = []
    window_id = None
    dimensions = None
    
    for command in commands:
        command = command.strip()
        if not command:
            continue
            
        # Handle special cases
        if command.startswith('WINDOW_ID='):
            window_id = execute_command('xdotool getactivewindow')
            continue
        
        # Replace $WINDOW_ID with actual value if we have it
        if window_id and '$WINDOW_ID' in command:
            command = command.replace('$WINDOW_ID', window_id)
            
        # Execute the command
        output = execute_command(command)
        if output:
            # Store window ID if this was a window ID query
            if command.strip() == 'xdotool getactivewindow':
                window_id = output
            # Parse dimensions if this was a dimensions query
            elif 'xdpyinfo | grep dimensions' in command:
                match = re.search(r'dimensions:\s+(\d+)x(\d+)', output)
                if match:
                    dimensions = (match.group(1), match.group(2))
            results.append(output)
    
    return "\n".join(results)

def AI(command, system_prompt, context=None):
    """Send a command to the AI model and get a response."""
    logging.info(f"Sending command to AI: {command}")
    
    if isinstance(context, str):
        context_messages = [{"role": "user", "content": context}]
    elif isinstance(context, list):
        context_messages = context
    else:
        context_messages = []
        
    context_str = "\n".join([
        f"<|start_header_id|>{msg['role']}<|end_header_id|> {msg['content']}<|eot_id|>"
        for msg in context_messages
    ])
    
    prompt = f"""<|start_header_id|>system<|end_header_id|>{system_prompt}<|eot_id|>
{context_str}
<|start_header_id|>user<|end_header_id|>{command}<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>"""

    try:
        response = requests.post('http://localhost:11434/api/generate',
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "stop": ["<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>"],
                    "num_predict": 8192
                }
            })
        
        if response.status_code == 200:
            ai_response = response.json()['response'].strip()
            logging.info(f"AI response: {ai_response}")
            return ai_response
        else:
            error_msg = f"Error calling Ollama API: {response.status_code} - {response.text}"
            logging.error(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"Error processing request: {str(e)}"
        logging.error(error_msg)
        return error_msg

def evaluate_request(raw_cmd):
    """Evaluate the request and gather necessary context"""
    logging.info(f"Evaluating request: {raw_cmd}")
    
    # Get evaluation from AI
    evaluation = AI(raw_cmd, evaluate_prompt)
    
    try:
        # Parse the evaluation JSON
        eval_data = json.loads(evaluation)
        logging.info(f"Parsed evaluation: {eval_data}")
        
        # Execute discovery commands and gather results
        context = {
            "original_request": raw_cmd,
            "command_outputs": {},
            "operation": eval_data.get("operation", "unknown")
        }
        
        if "discovery_commands" in eval_data:
            for cmd in eval_data["discovery_commands"]:
                output = execute_command(cmd)
                context["command_outputs"][cmd] = output
                logging.info(f"Discovery command output - {cmd}: {output}")
        
        if "purpose" in eval_data:
            context["purpose"] = eval_data["purpose"]
            
        return context
        
    except json.JSONDecodeError:
        error_msg = f"Error parsing evaluation JSON: {evaluation}"
        logging.error(error_msg)
        return {
            "original_request": raw_cmd,
            "error": "Failed to parse evaluation response",
            "operation": "unknown"
        }

def process(raw_cmd):
    """Process a user command"""
    global last_from_ai, CMD_history
    logging.info(f"Processing command: {raw_cmd}")
    
    CMD_history.append(raw_cmd)
    
    # First, evaluate the request and gather context
    context = evaluate_request(raw_cmd)
    
    # Add command history to context
    history_context = format_context(CMD_history, last_from_ai)
    if history_context:
        context['history'] = history_context
    
    # Format context for execution phase
    execution_context = json.dumps(context, indent=2)
    question = f"Context: {execution_context}\nUser CMD: {raw_cmd}"
    logging.info(f"Execution context: {question}")
    
    # Get AI response for execution
    response = AI(question, execute_prompt)
    logging.info(f"Commands to execute: {response}")
    
    # Execute the commands
    last_from_ai = process_commands(response)
    
    if last_from_ai:
        logging.info(f"Command output: {last_from_ai}")

def format_context(cmd_history, last_reply):
    """Format command history and last reply into a context string"""
    context = []
    
    if cmd_history:
        cmd_history_formatted = "', '".join(cmd_history)
        context.append(f"Past cmds: '{cmd_history_formatted}'")
    
    if last_reply:
        context.append(f"Last reply: {last_reply}")
        
    return "\n".join(context)

def main():
    """Main loop to process commands"""
    logging.info("Starting desktop controller")
    process(f"Call me {username}")
    
    while YOLO:
        if os.path.exists(heard_file):
            with open(heard_file, "r") as f:
                cmd = f.read().strip()
            os.remove(heard_file)
            if cmd:
                process(cmd)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        print("\nShutting down...")
