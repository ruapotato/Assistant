import os
import pwd
import json
import requests
import re
import subprocess
import time

username = pwd.getpwuid(os.getuid()).pw_name
heard_file = "./heard"
voice_dir = "./voice"
MODEL = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
YOLO = True
CMD_history = []
last_from_ai = ""

# Updated evaluation prompt to better handle typing commands
evaluate_prompt = """You are a Linux System Analyzer that helps prepare context for command execution.
Your job is to:
1. Run specific commands to gather context based on the request
2. Return the commands and their expected outputs as structured data

Common scenarios to handle:
- For Active app text which is normal to grab: Always run "import -window $(xdotool getactivewindow) png:- | tesseract stdin stdout"
- For clipboard/highlighted text requests: Always run "xclip -o -selection primary" for highlighted text and "xclip -o -selection clipboard" for clipboard
- For file info requests: Run "cat" or "ls" as needed
- For system info requests: Run appropriate system commands
- For transcription requests: Return transcribe mode with no commands
- For typing requests: Check if command starts with "Type in" or similar phrases

Output format must be JSON with:
1. "commands": Array of commands to run
2. "purpose": Brief description of what each command is for
3. "mode": String indicating the type of operation ("summarize", "speak", "type", "transcribe", etc.)

Example outputs:
For "Summarize clipboard":
{
    "commands": ["xclip -o -selection clipboard"],
    "purpose": "Getting clipboard content for summarization",
    "mode": "summarize"
}

For "Tell me about file test.txt":
{
    "commands": ["cat test.txt"],
    "purpose": "Reading file content",
    "mode": "speak"
}

For "Type in Hello world":
{
    "commands": [],
    "purpose": "Typing text directly",
    "mode": "type",
    "text": "Hello world"
}

For "Call me David":
{
    "commands": [],
    "purpose": "NA",
    "mode": "speak"
}

For "Transcribe what I say":
{
    "commands": [],
    "purpose": "Ready to transcribe speech",
    "mode": "transcribe"
}
For "Help me debug this":
{
    "commands": ["import -window $(xdotool getactivewindow) png:- | tesseract stdin stdout"],
    "purpose": "Read the error in the active app",
    "mode": "speak"
}
For "What do you think about this?":
{
    "commands": ["import -window $(xdotool getactivewindow) png:- | tesseract stdin stdout", "xclip -o -selection clipboard"],
    "purpose": "Pull in data the user might be talking about",
    "mode": "speak"
}

Must output valid JSON only - no other text.
For typing commands, extract the text after "Type in" and include it in the "text" field."""

# Updated execution prompt to better handle typing mode
execute_prompt = """You are a Linux Admin AI that helps users interact with their system.
You must respond in one of these formats based on the context mode:

For "speak" mode:
espeak 'your message'
espeak 'xclip -o output' # If asked to read selected

For "summarize" mode:
espeak "Here's the summary:"
espeak 'First key point'
espeak 'Second key point'
[etc...]

For "type" mode:
xdotool type "your text"
xdotool key "Return"  # When needed

For "transcribe" mode:
xdotool type "Text to transcribe"
xdotool key "Return"  # Add newline after transcription

Rules:
1. For summaries, break them into short, clear points that espeak can handle
2. Never output raw text - always use espeak or xdotool
3. Keep espeak messages under 100 characters for clarity
4. For multi-line output use separate espeak commands
5. For type mode, use the exact text provided in the context
6. For transcribe mode, format the text naturally with proper capitalization and punctuation

Example good summary output:
espeak "Here's the summary of the text:"
espeak "The story follows Arthur Dent escaping Earth's destruction"
espeak "He joins his friend Ford Prefect on a galactic adventure"
espeak "They discover the answer to life is 42"

Example type mode output:
xdotool type "Hello world"
xdotool key "Return"

Example transcribe output:
xdotool type "Today I learned about quantum computing and its potential applications."
xdotool key "Return"

Never add explanations - only output valid commands."""

def execute_command(command):
    """Execute a command and return its output"""
    try:
        # For espeak commands, execute without capturing output
        if command.startswith('espeak'):
            subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.5)  # Increased delay for better speech spacing
            return ""
            
        # For xdotool commands, execute without capturing output
        elif command.startswith('xdotool'):
            subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.1)
            return ""
            
        # For other commands, capture and return output
        else:
            result = subprocess.run(command, shell=True, text=True, capture_output=True)
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"Error: {result.stderr.strip()}"
            
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"

def process_commands(text):
    """Process commands from AI response"""
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
    
    # Execute each command
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

def evaluate_request(raw_cmd):
    """Evaluate the request and gather necessary context"""
    # Get evaluation from AI
    evaluation = AI(raw_cmd, evaluate_prompt)
    
    try:
        # Parse the evaluation JSON
        eval_data = json.loads(evaluation)
        
        # Execute each command and gather results
        context = {
            "original_request": raw_cmd,
            "command_outputs": {},
            "mode": eval_data.get("mode", "speak")  # Default to speak mode
        }
        
        # Add text field for typing commands
        if "text" in eval_data:
            context["text"] = eval_data["text"]
        
        if "commands" in eval_data:
            for cmd in eval_data["commands"]:
                output = execute_command(cmd)
                context["command_outputs"][cmd] = output
        
        if "purpose" in eval_data:
            context["purpose"] = eval_data["purpose"]
            
        return context
        
    except json.JSONDecodeError:
        print(f"Error parsing evaluation JSON: {evaluation}")
        return {
            "original_request": raw_cmd,
            "error": "Failed to parse evaluation response",
            "mode": "speak"
        }

def process(raw_cmd):
    """Process a user command"""
    global last_from_ai, CMD_history
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
    print(question)
    
    # Get AI response for execution
    response = AI(question, execute_prompt)
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
        print("\nShutting down...")
