import time
import os
import subprocess
import ollama
import json
import re

# Initialize Ollama client
ollama_client = ollama.Client()

# Load the specified model
MODEL_NAME = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
ollama_client.pull(MODEL_NAME)

# Context management
context = {
    "user_name": None,
    "last_result": None,
    "conversation_history": []
}

VOICE_DIR = "./voice/"
TRIGGER_FILE = "./trigger"
HEARD_FILE = "./heard"

# Ensure VOICE_DIR exists
if not os.path.exists(VOICE_DIR):
    os.makedirs(VOICE_DIR)
    print(f"Created directory: {VOICE_DIR}")

def say(text):
    filename = f"{int(time.time())}.txt"
    file_path = os.path.join(VOICE_DIR, filename)
    with open(file_path, 'w') as file:
        file.write(text)
    print(f"Queued for speech: {text}")

def type_text(text):
    print(f"Executing: xdotool type \"{text}\"")
    subprocess.run(['xdotool', 'type', text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def look():
    try:
        result = subprocess.run(['qdbus', 'org.gnome.Shell', '/org/gnome/Shell', 'org.gnome.Shell.Eval', 'global.get_window_actors().map(a=>a.meta_window.get_title())'], capture_output=True, text=True, check=True)
        active_window = json.loads(result.stdout)
        if active_window:
            return active_window[0]
        else:
            return "No active window found"
    except subprocess.CalledProcessError:
        return "Error getting active window information"

def process_llm_response(response):
    actions = []
    pattern = r'<(say|type)>(.*?)</\1>'
    matches = re.findall(pattern, response, re.DOTALL)
    
    for action, content in matches:
        actions.append((action, content.strip()))
    
    if not actions:
        # If no tags found, treat the entire response as speech
        actions.append(("say", response.strip()))
    
    return actions

def execute_actions(actions):
    for action, content in actions:
        if action == "say":
            say(content)
        elif action == "type":
            if not content and context["last_result"]:
                content = str(context["last_result"])
            type_text(content)
        elif action == "look":
            result = look()
            say(f"The active window is: {result}")

def update_context(command, response):
    context["conversation_history"].append({"command": command, "response": response})
    if len(context["conversation_history"]) > 5:  # Keep last 5 interactions
        context["conversation_history"].pop(0)
    
    # Update user name if set
    if "Call me" in command:
        name = command.split("Call me")[-1].strip().split()[0]
        context["user_name"] = name
    
    # Update last result if it's a calculation
    if "times" in command:
        try:
            result = eval(command.replace("What's ", "").replace("What is ", "").replace("?", ""))
            context["last_result"] = result
        except:
            pass

def process_command(command):
    # Prepare the prompt for the LLM
    conversation_history = "\n".join([f"User: {item['command']}\nAssistant: {item['response']}" for item in context["conversation_history"]])
    prompt = f"""Conversation history:
{conversation_history}

Current context:
User name: {context['user_name'] or 'Unknown'}
Last calculation result: {context['last_result']}

User request: {command}
Be short and to the point. Respond using <say> tags for speech output. Use <type> tags when explicitly asked to type something or when the command starts with "Type".
For example:
- If asked "What's 5 times 5?", respond with: <say>5 times 5 is 25.</say>
- If asked "Type the result of 5 times 5", respond with: <say>Sure!</say><type>25</type>
- If asked "Type, I love Molly Hamner", respond with: <type>I love Molly Hamner</type>
- If asked "Thank you.", respond with: <say>Happy to help!</say>
"""

    # Get response from Ollama
    response = ollama_client.generate(MODEL_NAME, prompt)
    
    # Debug: Print model output
    print("Model output:", response['response'])

    # Update context
    update_context(command, response['response'])

    # Process the LLM response
    actions = process_llm_response(response['response'])

    # Execute the actions
    execute_actions(actions)

def read_trigger_file():
    try:
        with open(TRIGGER_FILE, "r") as f:
            content = f.read().strip()
        return content
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading trigger file: {e}")
        return None

def read_heard_file():
    try:
        with open(HEARD_FILE, "r") as f:
            content = f.read().strip()
        return content
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error reading heard file: {e}")
        return None

def main():
    last_processed = ""
    last_trigger_state = None
    
    while True:
        # Check for new trigger
        trigger_state = read_trigger_file()
        if trigger_state and trigger_state != last_trigger_state:
            print(f"New trigger state detected: {trigger_state}")
            last_trigger_state = trigger_state

        # Check for new command
        heard_content = read_heard_file()
        if heard_content and heard_content != last_processed:
            print(f"Processing command: {heard_content}")
            process_command(heard_content)
            last_processed = heard_content
        
        time.sleep(0.1)  # Check for new content every 100ms

if __name__ == "__main__":
    main()
