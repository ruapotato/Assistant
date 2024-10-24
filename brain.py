import os
import pwd
import json
import requests
import pexpect
import re
import time

username = pwd.getpwuid(os.getuid()).pw_name
heard_file = "./heard"
voice_dir = "./voice"
MODEL = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
YOLO = True
CMD_history = []
last_from_ai = ""
vert_term = None  # Global terminal variable

# Updated system prompt to output only commands
system_prompt = """You are a Linux Admin AI that ONLY responds with bash commands. Never add any explanation text.
To speak, use: espeak 'your message'
To execute system commands, just write the command
To type something: xdotool type 'hello'

Examples of valid question -> responses:
Call me David -> espeak 'Welcome David.'
Type in a joke -> xdotool type "Your best joke"
Tell me a joke -> espeak "Your best joke"
Where am I -> espeak "you are in $(pwd)"
Read highlighted text -> espeak "$(xclip -o)"

For multi line output use one xdotool command per line, with a `xdotool key "Return"` every ohter line. 
xdotool type "Line one"
xdotool key "Return"
xdotool type "Line two"
xdotool key "Return"
xdotool type "Line three"

Every response must be one or more bash commands.
Never wrap commands in quotes unless part of the command syntax itself.
Never add explanations - only output valid bash commands. 
Prefer espeak to reply"""

# Ensure voice directory exists
os.makedirs(voice_dir, exist_ok=True)

def start_terminal():
    """Start a new bash session and return the terminal"""
    global vert_term
    vert_term = pexpect.spawn('bash', encoding='utf-8')
    vert_term.expect('[$#] ')  # Wait for prompt
    return vert_term

def execute_command(command):
    """Execute a command in the terminal and return its output"""
    global vert_term
    if not vert_term:
        return "Terminal not started"
        
    try:
        # Send Ctrl+C to ensure clean prompt
        vert_term.sendcontrol('c')
        vert_term.expect('[$#] ', timeout=1)
        
        print(f"Executing: {command}")
        vert_term.sendline(command)
        
        # For espeak commands, don't wait for output
        if command.startswith('espeak'):
            time.sleep(0.1)  # Small delay to ensure command starts
            vert_term.expect('[$#] ', timeout=1)
            return ""
            
        # For xdotool commands, shorter timeout
        elif command.startswith('xdotool'):
            vert_term.expect('[$#] ', timeout=2)
            return ""
            
        # For other commands, normal timeout
        else:
            vert_term.expect('[$#] ', timeout=5)
            # Skip the first line as it contains the command echo
            output = vert_term.before.split('\n', 1)[1].rsplit('\n', 1)[0] if '\n' in vert_term.before else ""
            return output.strip()
            
    except pexpect.TIMEOUT:
        # Don't treat timeout as error for espeak/xdotool
        if command.startswith(('espeak', 'xdotool')):
            return ""
        return "Command timed out"
    except pexpect.EOF:
        return "Terminal closed unexpectedly"
    except Exception as e:
        return f"Error: {str(e)}"
            
    except pexpect.TIMEOUT:
        # Don't treat timeout as error for espeak/xdotool
        if command.startswith(('espeak', 'xdotool')):
            return ""
        return "Command timed out"
    except pexpect.EOF:
        return "Terminal closed unexpectedly"
    except Exception as e:
        return f"Error: {str(e)}"

def process_commands(text):
    """Process commands from AI response"""
    # Split into individual commands if multiple are present
    commands = re.split(r'(?<!&)(?<!&)\s*&&\s*|\s*;\s*', text.strip())
    results = []
    
    for command in commands:
        command = command.strip()
        if command:
            output = execute_command(command)
            if output:
                results.append(output)
    
    return "\n".join(results)

def AI(command, system_prompt, context=None):
    """Send a command to the AI model and get a response."""
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
            return response.json()['response'].strip()
        else:
            return f"Error calling Ollama API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error processing request: {str(e)}"

def process(raw_cmd):
    """Process a user command"""
    global last_from_ai, CMD_history
    CMD_history.append(raw_cmd)
    
    context = format_context(CMD_history, last_from_ai)
    question = f"User CMD: {raw_cmd}"
    print(question)
    
    # Get AI response
    response = AI(question, system_prompt, context=context)
    print(f"Commands to execute: {response}")
    
    # Execute the commands
    last_from_ai = process_commands(response)
    
    if last_from_ai:
        print(f"Command output: {last_from_ai}")

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
    start_terminal()
    process(f"Call me {username}")
    
    while YOLO:
        if os.path.exists(heard_file):
            with open(heard_file, "r") as f:
                cmd = f.read().strip()
            os.remove(heard_file)
            if cmd:
                process(cmd)

if __name__ == "__main__":
    cleanup_done = False
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if vert_term and not cleanup_done:
            vert_term.close()
            cleanup_done = True
