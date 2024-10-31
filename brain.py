import os
import pwd
import json
import requests
import pexpect
import re
import time

username = pwd.getpwuid(os.getuid()).pw_name
heard_file = "./heard"
voice_dir = "./voice/"
MODEL = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
YOLO = True
CMD_history = []
last_from_ai = ""
vert_term = None

# Updated system prompt with clearer instructions
system_prompt = """You are a voice-controlled assistant that responds to commands and provides information.
When responding:
1. Use 'say:' for all user-directed communication
2. Use 'run:' only when a command needs to be executed
3. Wait for command output before providing analysis
4. Never repeat or re-run commands that were just executed
5. Keep responses concise and natural
6. Don't announce command execution - just run them when needed

Example good response to "list files":
run: ls -al

Example good response to command output:
say: I see 5 Python files and 2 directories. The largest file is...

To get highlighted text use "xclip -o -selection primary"
If asked to read selected text, start with the xclip command
To minimize the active window, start by running "xdotool getactivewindow" then move onto using "xdotool windowminimize ID"
If asked to type use xdotool, not espeak
If asked to read use espeak, not xdotool

Remember: One say/run command per line, no explanations of what you're about to do. use 'say' most of the time"""

os.makedirs(voice_dir, exist_ok=True)

def AI(command, system_prompt, context=None):
    """Send a command to the AI model and get a response."""
    if isinstance(context, str):
        context_messages = [{"role": "user", "content": context}]
    elif isinstance(context, list):
        context_messages = context
    else:
        context_messages = []
    
    # Format context ensuring proper order of messages
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

def say(a_thing_to_say):
    """Write text to voice file with timestamp."""
    timestamp = int(time.time() * 1000)
    file_path = os.path.join(voice_dir, f"speech_{timestamp}.txt")
    try:
        with open(file_path, 'w') as f:
            f.write(str(a_thing_to_say))
    except Exception as e:
        print(f"Error writing to voice file: {e}")

def format_context(cmd_history):
    """Format command history maintaining proper message order."""
    context = []
    
    for entry in cmd_history:
        # Add the user command first
        if 'cmd' in entry:
            context.append({
                "role": "user",
                "content": entry['cmd']
            })
        
        # Add command output if present
        if 'stdout' in entry:
            context.append({
                "role": "stdout",
                "content": entry['stdout']
            })
        
        # Add AI response if present
        if 'response' in entry:
            context.append({
                "role": "assistant",
                "content": entry['response']
            })
    
    return context

def process(raw_cmd, cmd_data=False):
    """Process commands while maintaining proper context and avoiding redundancy."""
    global last_from_ai, CMD_history
    
    # Create new history entry
    current_entry = {}
    if cmd_data:
        current_entry['stdout'] = raw_cmd
    else:
        current_entry['cmd'] = raw_cmd
    
    # Store last AI response before adding new command
    if last_from_ai and CMD_history:
        CMD_history[-1]['response'] = last_from_ai
    
    # Add new entry to history
    CMD_history.append(current_entry)
    
    # Get context and format question
    context = format_context(CMD_history)
    question = raw_cmd if cmd_data else f"User command: {raw_cmd}"
    print(question)
    
    # Get AI response
    response = AI(question, system_prompt, context=context)
    print(response)
    last_from_ai = response
    
    # Process response lines
    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("say:"):
            say(line[4:].strip())
        elif line.startswith("run:"):
            cmd_output = os.popen(line[4:].strip()).read()
            if cmd_output:
                process(cmd_output, cmd_data=True)
    
    return response

def main():
    """Main loop for processing voice commands."""
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
