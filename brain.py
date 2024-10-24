import os
import json
import logging
import subprocess
import select
import signal
import asyncio
import requests
import time
import traceback
import re
import glob
import getpass
import pty
import termios
import fcntl
import struct
import errno
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

class Colors:
    """Terminal colors and styles"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    
    @classmethod
    def format(cls, text: str, color: str, bold: bool = False) -> str:
        """Format text with color and optional bold"""
        style = cls.BOLD if bold else ''
        return f"{style}{color}{text}{cls.ENDC}"

@dataclass
class CommandState:
    """Tracks command execution state and outputs"""
    last_command: Optional[str] = None
    last_output: Optional[str] = None
    last_error: Optional[str] = None
    command_history: List[str] = None
    output_history: List[str] = None

    def __init__(self):
        self.command_history = []
        self.output_history = []

class VirtualTerminal:
    """Manages a virtual terminal session"""
    def __init__(self):
        # Create virtual terminal
        self.master_fd, self.slave_fd = pty.openpty()
        
        # Set terminal attributes
        term_settings = termios.tcgetattr(self.slave_fd)
        term_settings[3] = term_settings[3] & ~termios.ECHO  # Disable echo
        termios.tcsetattr(self.slave_fd, termios.TCSANOW, term_settings)
        
        # Start bash session
        self.shell_pid = os.fork()
        if self.shell_pid == 0:  # Child process
            os.close(self.master_fd)
            os.setsid()
            os.dup2(self.slave_fd, 0)
            os.dup2(self.slave_fd, 1)
            os.dup2(self.slave_fd, 2)
            os.execvp('bash', ['bash'])
        else:  # Parent process
            os.close(self.slave_fd)
            
        # Set non-blocking mode
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        # Buffer for terminal output
        self.output_buffer = ""
        
        # Initialize terminal
        self.write("export PS1='$ '\n")  # Set a simple prompt
        self.read(timeout=0.5)  # Clear initial output

    def write(self, data: str):
        """Write to virtual terminal"""
        os.write(self.master_fd, data.encode())

    def read(self, timeout: float = 0.1) -> str:
        """Read from virtual terminal with timeout"""
        output = []
        start_time = time.time()
        
        while True:
            try:
                if select.select([self.master_fd], [], [], timeout)[0]:
                    data = os.read(self.master_fd, 1024).decode()
                    if data:
                        output.append(data)
                    else:
                        break
                elif time.time() - start_time > timeout:
                    break
            except (OSError, IOError) as e:
                if e.errno != errno.EAGAIN:
                    raise
                if time.time() - start_time > timeout:
                    break
                time.sleep(0.01)
                
        return "".join(output)

    def get_screen_content(self) -> str:
        """Get current screen content"""
        # Clear screen and move cursor to home position
        self.write("\x1b[2J\x1b[H")
        time.sleep(0.1)
        
        # Send command to show current content
        self.write("echo $?\n")  # Get last command's exit status
        time.sleep(0.1)
        
        # Read output
        output = self.read(timeout=0.5)
        
        # Clean up output by removing prompt and command
        lines = output.split('\n')
        cleaned_lines = [line for line in lines if line.strip() and not line.strip().startswith('$')]
        return '\n'.join(cleaned_lines)

    def cleanup(self):
        """Clean up virtual terminal"""
        try:
            os.kill(self.shell_pid, signal.SIGTERM)
            os.close(self.master_fd)
        except:
            pass

class Node:
    """LLM interface for command generation and output analysis"""
    def __init__(self, model_name: str, name: str, max_tokens: int = 8192):
        self.model_name = model_name
        self.name = name
        self.definition = ""
        self.context = []
        self.max_tokens = max_tokens

    def __call__(self, input_text: str, additional_data: dict = None):
        try:
            context_str = "\n".join([f"<|start_header_id|>{msg['role']}<|end_header_id|> {msg['content']}<|eot_id|>" for msg in self.context])
            
            prompt = f"""<|start_header_id|>system<|end_header_id|>{self.definition}<|eot_id|>
{context_str}
<|start_header_id|>user<|end_header_id|>{input_text}<|eot_id|>"""

            if additional_data:
                prompt += "\n<|start_header_id|>system<|end_header_id|>Additional data:\n"
                for key, value in additional_data.items():
                    prompt += f"{key}: {value}\n"
                prompt += "<|eot_id|>"

            prompt += "\n<|start_header_id|>assistant<|end_header_id|>"

            response = requests.post('http://localhost:11434/api/generate', 
                                     json={
                                         "model": self.model_name,
                                         "prompt": prompt,
                                         "stream": False,
                                         "options": {
                                             "stop": ["<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>"],
                                             "num_predict": self.max_tokens
                                         }
                                     })
            
            if response.status_code == 200:
                output = response.json()['response'].strip()
                self.context.append({"role": "user", "content": input_text})
                self.context.append({"role": "assistant", "content": output})
                return output
            else:
                return f"Error in Ollama API call: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Error in processing: {str(e)}"

class CommandReviewer:
    """Handles intelligent review of command execution using LLM"""
    def __init__(self, model_name: str):
        self.reviewer = Node(model_name, "Command Reviewer")
        self.initialize_reviewer()

    def initialize_reviewer(self):
        """Initialize the command reviewer's context and behavior"""
        self.reviewer.definition = """
        You are an expert at reviewing command execution results in real-time.
        Your job is to determine if a command has finished executing and analyze its output.

        INSTRUCTIONS:
        1. Look for signs of command completion:
           - Presence of shell prompt ($ or #)
           - Absence of typical "in progress" indicators
           - No partial output lines
           - No spinning indicators or progress bars
        2. Analyze the actual command output for:
           - Success/failure indicators
           - Error messages
           - Expected output patterns
           - Completion messages
        
        Return ONLY a JSON object with this structure:
        {
            "command_complete": true/false,
            "needs_more_time": true/false,
            "success": true/false,
            "error_detected": true/false,
            "error_message": "description if error found",
            "output_analysis": "brief analysis of current output",
            "suggested_wait_time": float (additional seconds to wait if needed)
        }
        """

    async def review_execution(self, command: str, current_screen: str, elapsed_time: float) -> dict:
        """Review the current command execution state"""
        analysis = self.reviewer(f"""
        Review this command execution:
        
        Original command: {command}
        Elapsed time: {elapsed_time:.1f} seconds
        
        Current screen content:
        {current_screen}
        
        Analyze the execution state and output.
        Consider the command type and expected behavior.
        IMPORTANT: Return only valid JSON in the specified format.
        """)
        
        try:
            # Clean and parse the JSON response
            json_str = analysis.strip()
            
            # Find the JSON object using regex
            json_match = re.search(r'\{[^}]+\}', json_str, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                # Remove any trailing commas before closing braces
                json_str = re.sub(r',(\s*})', r'\1', json_str)
                # Clean up any newlines and extra spaces
                json_str = re.sub(r'\s+', ' ', json_str)
                
            result = json.loads(json_str)
            
            # Ensure all required fields are present
            required_fields = [
                'command_complete', 'needs_more_time', 'success',
                'error_detected', 'error_message', 'output_analysis',
                'suggested_wait_time'
            ]
            for field in required_fields:
                if field not in result:
                    if field in ['command_complete', 'needs_more_time', 'success', 'error_detected']:
                        result[field] = False
                    elif field == 'suggested_wait_time':
                        result[field] = 0.0
                    else:
                        result[field] = ""
            
            return result
            
        except (json.JSONDecodeError, AttributeError) as e:
            logging.error(f"Failed to parse reviewer output: {analysis}")
            logging.error(f"JSON parsing error: {str(e)}")
            
            # Try to extract meaningful information from the failed parse
            success_indication = "success" in analysis.lower() and "error" not in analysis.lower()
            error_message = str(e)
            output_summary = analysis[:200] + "..." if len(analysis) > 200 else analysis
            
            return {
                "command_complete": True,
                "needs_more_time": False,
                "success": success_indication,
                "error_detected": not success_indication,
                "error_message": error_message,
                "output_analysis": output_summary,
                "suggested_wait_time": 0.0
            }

class TerminalAssistant:
    def __init__(self):
        self.MODEL_NAME = "hf.co/bartowski/Replete-LLM-V2.5-Qwen-7b-GGUF:Q5_K_S"
        
        # Convert relative paths to absolute paths at initialization
        self.current_directory = os.path.abspath(os.getcwd())
        self.VOICE_DIR = os.path.abspath("./voice/")
        self.TRIGGER_FILE = os.path.abspath("./trigger")
        self.HEARD_FILE = os.path.abspath("./heard")
        
        # Initialize virtual terminal
        self.vt = VirtualTerminal()
        
        # Initialize state and nodes
        self.state = CommandState()
        self.command_executor = Node(self.MODEL_NAME, "Command Executor")
        self.output_analyzer = Node(self.MODEL_NAME, "Output Analyzer")
        
        # Initialize command reviewer
        self.command_reviewer = CommandReviewer(self.MODEL_NAME)
        
        # Setup directories and initialize
        os.makedirs(self.VOICE_DIR, exist_ok=True)
        self.initialize_system_context()

    def initialize_system_context(self):
        """Initialize system context for AI nodes"""
        # Get system information
        system_info = subprocess.check_output("uname -a", shell=True, text=True).strip()
        desktop_env = os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown')

        # Command Executor context
        self.command_executor.definition = f"""
        You are an AI terminal assistant that can use any command available on Debian.
        Current system: {system_info}
        Desktop environment: {desktop_env}
        Working directory: {self.current_directory}

        CAPABILITIES:
        1. You can use any command available on Debian
        2. You can use xdotool for typing if needed
        3. You have access to a full bash session
        4. You can use any terminal program
        
        INSTRUCTIONS:
        1. When given a task, generate appropriate command(s) to accomplish it
        2. IMPORTANT: For multiple commands, join them with " && " (space before and after)
        3. For typing character by character, use a single command with sleep:
           Example: for c in $(echo "hello" | grep -o .); do xdotool type "$c" && sleep 0.1; done
        4. Return ONLY the command(s) to execute, no explanations
        5. Ensure all paths are absolute
        6. Always return a single line command (use && or semicolons to separate multiple commands)
        7. For xdotool commands, always include complete window specification
        
        EXAMPLES:
        User: "Type hello character by character"
        Return: for c in $(echo "hello" | grep -o .); do xdotool type --clearmodifiers "$c" && sleep 0.2; done

        User: "Create a directory and list its contents"
        Return: mkdir -p /path/to/dir && ls -la /path/to/dir

        User: "Type a message with delay"
        Return: xdotool type --clearmodifiers --delay 100 "Hello world"
        """

        # Output Analyzer context
        self.output_analyzer.definition = """
        You are an expert at analyzing terminal output and determining success or failure.
        ALWAYS return your analysis in valid JSON format.
        
        INSTRUCTIONS:
        1. Analyze the provided terminal screen content
        2. Look for common error patterns:
           - "command not found"
           - "permission denied"
           - "no such file or directory"
           - Error messages in red
           - Stack traces
        3. Consider the context of the original command
        4. Return ONLY a JSON object with this exact structure:
        {
            "success": true/false,
            "error_message": "description of error if any",
            "suggested_fix": "suggestion if error occurred",
            "output_summary": "brief summary of what happened"
        }

        Example response for success:
        {"success":true,"error_message":"","suggested_fix":"","output_summary":"File created successfully"}

        Example response for failure:
        {"success":false,"error_message":"Permission denied","suggested_fix":"Try using sudo","output_summary":"Command failed due to permissions"}
        """

    def say(self, text: str):
        """Queue text for speech output"""
        filename = f"{int(time.time())}.txt"
        file_path = os.path.join(self.VOICE_DIR, filename)
        with open(file_path, 'w') as file:
            file.write(text)
        logging.info(f"Queued for speech: {text}")

    async def execute_command(self, command: str) -> dict:
        """Execute command with intelligent review and dynamic waiting"""
        MAX_WAIT_TIME = 30.0  # Maximum total wait time
        INITIAL_WAIT = 0.5    # Initial wait before first check
        
        # Write command to terminal
        self.vt.write(f"{command}\n")
        
        # Initial wait
        await asyncio.sleep(INITIAL_WAIT)
        
        start_time = time.time()
        total_elapsed = 0.0
        
        while total_elapsed < MAX_WAIT_TIME:
            # Get current screen content
            screen_content = self.vt.get_screen_content()
            
            # Review current execution state
            review = await self.command_reviewer.review_execution(
                command, screen_content, total_elapsed
            )
            
            if review['command_complete']:
                # Command finished, perform final analysis
                final_analysis = self.output_analyzer(f"""
                Original command: {command}
                Final output:
                {screen_content}
                
                Command completed in {total_elapsed:.1f} seconds.
                Reviewer analysis: {review['output_analysis']}
                
                Provide final analysis in JSON format.
                """)
                
                try:
                    result = json.loads(final_analysis)
                    result['execution_time'] = total_elapsed
                    return result
                except json.JSONDecodeError:
                    return {
                        "success": review['success'],
                        "error_message": review['error_message'],
                        "suggested_fix": "",
                        "output_summary": review['output_analysis'],
                        "execution_time": total_elapsed
                    }
            
            # Command not complete, wait as suggested
            wait_time = min(
                review['suggested_wait_time'] if review['suggested_wait_time'] > 0 else 0.5,
                MAX_WAIT_TIME - total_elapsed
            )
            await asyncio.sleep(wait_time)
            total_elapsed = time.time() - start_time
        
        # Timeout case
        return {
            "success": False,
            "error_message": "Command timed out",
            "suggested_fix": "Consider using timeout command or breaking into smaller steps",
            "output_summary": "Execution exceeded maximum wait time",
            "execution_time": total_elapsed
        }

    async def process_request(self, user_input: str):
        """Process user request and execute appropriate commands"""
        try:
            # Generate command(s)
            command = self.command_executor(user_input)
            print(f"\n{Colors.format('Generated command:', Colors.BLUE, bold=True)} {command}")
            
            # Execute command and analyze result
            result = await self.execute_command(command)
            
            # Update state
            self.state.last_command = command
            self.state.last_output = result.get('output_summary', '')
            self.state.last_error = result.get('error_message', '')
            self.state.command_history.append(command)
            self.state.output_history.append(result.get('output_summary', ''))
            
            # Display result
            if result['success']:
                print(f"\n{Colors.format('Success:', Colors.GREEN, bold=True)} {result['output_summary']}")
                self.say(f"Command completed: {result['output_summary']}")
            else:
                print(f"\n{Colors.format('Error:', Colors.RED, bold=True)} {result['error_message']}")
                if result.get('suggested_fix'):
                    print(f"{Colors.format('Suggested fix:', Colors.YELLOW, bold=True)} {result['suggested_fix']}")
                self.say(f"Command failed: {result['error_message']}")
            
            return result['success']
            
        except Exception as e:
            error_msg = f"Error processing request: {str(e)}"
            logging.error(f"{error_msg}\n{traceback.format_exc()}")
            print(f"\n{Colors.format('Error:', Colors.RED, bold=True)} {error_msg}")
            self.say(f"Error occurred: {error_msg}")
            return False

    async def main(self):
        """Main loop"""
        print(Colors.format("AI Terminal Assistant", Colors.HEADER, bold=True))
        print(Colors.format("Listening for voice commands...", Colors.BLUE))
        self.say("AI Terminal Assistant ready")
        
        last_trigger_state = None
        last_heard_content = None
        
        try:
            while True:
                # Check for voice input
                trigger_state = self.read_trigger_file()
                if trigger_state != last_trigger_state:
                    logging.info(f"Trigger state changed to: {trigger_state}")
                    last_trigger_state = trigger_state
                
                # Check for commands
                heard_content = self.read_heard_file()
                if heard_content and heard_content != last_heard_content:
                    logging.info(f"Processing command: {heard_content}")
                    print(Colors.format(f"\nProcessing: {heard_content}", Colors.BLUE, bold=True))
                    
                    # Process the request
                    await self.process_request(heard_content)
                    
                    last_heard_content = heard_content
                
                await asyncio.sleep(0.1)
                    
        except KeyboardInterrupt:
            print(Colors.format("\nShutting down...", Colors.YELLOW))
        except Exception as e:
            error_msg = f"Error in main loop: {str(e)}\n{traceback.format_exc()}"
            logging.error(error_msg)
            print(Colors.format(f"\nError: {str(e)}", Colors.RED))
        finally:
            self.vt.cleanup()

    def read_trigger_file(self):
        try:
            with open(self.TRIGGER_FILE, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def read_heard_file(self):
        try:
            if os.path.exists(self.HEARD_FILE):
                with open(self.HEARD_FILE, "r") as f:
                    content = f.read().strip()
                os.remove(self.HEARD_FILE)
                return content
            return None
        except Exception as e:
            logging.error(f"Error reading heard file: {e}")
            return None

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('brain.log')
        ]
    )
    
    assistant = TerminalAssistant()
    asyncio.run(assistant.main())
