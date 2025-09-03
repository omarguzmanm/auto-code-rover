"""
Interfacing with OpenAI models.
"""

import json
import os
import sys
from typing import Literal, cast

from litellm import NotGiven
from loguru import logger
from openai import NOT_GIVEN, BadRequestError, OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
)
from openai.types.chat.chat_completion_message_tool_call import (
    Function as OpenaiFunction,
)
from openai.types.chat.chat_completion_tool_choice_option_param import (
    ChatCompletionToolChoiceOptionParam,
)
from openai.types.chat.completion_create_params import ResponseFormat
from tenacity import retry, stop_after_attempt, wait_random_exponential

# Azure AI Inference imports for DeepSeek
try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
    from azure.core.credentials import AzureKeyCredential
    AZURE_AI_AVAILABLE = True
except ImportError:
    AZURE_AI_AVAILABLE = False

from app.data_structures import FunctionCallIntent
from app.log import log_and_print
from app.model import common
from app.model.common import Model


class OpenaiModel(Model):
    """
    Base class for creating Singleton instances of OpenAI models.
    We use native API from OpenAI instead of LiteLLM.
    """

    _instances = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
            cls._instances[cls]._initialized = False
        return cls._instances[cls]

    def __init__(
        self,
        name: str,
        max_output_token: int,
        cost_per_input: float,
        cost_per_output: float,
        parallel_tool_call: bool = False,
    ):
        if self._initialized:
            return
        super().__init__(name, cost_per_input, cost_per_output, parallel_tool_call)
        # max number of output tokens allowed in model response
        # sometimes we want to set a lower number for models with smaller context window,
        # because output token limit consumes part of the context window
        self.max_output_token = max_output_token
        # client for making request
        self.client: OpenAI | None = None
        self._initialized = True

    def setup(self) -> None:
        """
        Check API key, and initialize OpenAI client for Azure.
        """
        if self.client is None:
            key = self.check_api_key()
            # Azure OpenAI configuration
            endpoint = "https://omara-mexwy2b2-eastus2.cognitiveservices.azure.com/openai/v1/"
            self.client = OpenAI(base_url=endpoint, api_key=key)

    def check_api_key(self) -> str:
        # Try Azure API key first, then fallback to standard
        key = os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        if not key:
            print("Please set the OPENAI_API_KEY or AZURE_OPENAI_API_KEY env var")
            sys.exit(1)
        return key

    def extract_resp_content(
        self, chat_completion_message: ChatCompletionMessage
    ) -> str:
        """
        Given a chat completion message, extract the content from it.
        """
        content = chat_completion_message.content
        if content is None:
            return ""
        else:
            return content

    def extract_resp_func_calls(
        self,
        chat_completion_message: ChatCompletionMessage,
    ) -> list[FunctionCallIntent]:
        """
        Given a chat completion message, extract the function calls from it.
        Args:
            chat_completion_message (ChatCompletionMessage): The chat completion message.
        Returns:
            List[FunctionCallIntent]: A list of function calls.
        """
        result = []
        tool_calls = chat_completion_message.tool_calls
        if tool_calls is None:
            return result

        call: ChatCompletionMessageToolCall
        for call in tool_calls:
            called_func: OpenaiFunction = call.function
            func_name = called_func.name
            func_args_str = called_func.arguments
            # maps from arg name to arg value
            if func_args_str == "":
                args_dict = {}
            else:
                try:
                    args_dict = json.loads(func_args_str, strict=False)
                except json.decoder.JSONDecodeError:
                    args_dict = {}
            func_call_intent = FunctionCallIntent(func_name, args_dict, called_func)
            result.append(func_call_intent)

        return result

    # FIXME: the returned type contains OpenAI specific Types, which should be avoided
    @retry(wait=wait_random_exponential(min=30, max=600), stop=stop_after_attempt(3))
    def call(
        self,
        messages: list[dict],
        top_p: float = 1,
        tools: list[dict] | None = None,
        response_format: Literal["text", "json_object"] = "text",
        temperature: float | None = None,
        **kwargs,
    ) -> tuple[
        str,
        list[ChatCompletionMessageToolCall] | None,
        list[FunctionCallIntent],
        float,
        int,
        int,
    ]:
        """
        Calls the openai API to generate completions for the given inputs.
        Assumption: we only retrieve one choice from the API response.

        Args:
            messages (List): A list of messages.
                            Each item is a dict (e.g. {"role": "user", "content": "Hello, world!"})
            top_p (float): The top_p to use. We usually do not vary this, so not setting it as a cmd-line argument. (from 0 to 1)
            tools (List, optional): A list of tools.

        Returns:
            Raw response and parsed components.
            The raw response is to be sent back as part of the message history.
        """
        if temperature is None:
            temperature = common.MODEL_TEMP

        assert self.client is not None
        try:
            if tools is not None and len(tools) == 1:
                # there is only one tool => force the model to use it
                tool_name = tools[0]["function"]["name"]
                tool_choice = {"type": "function", "function": {"name": tool_name}}
                response: ChatCompletion = self.client.chat.completions.create(
                    model=self.name,
                    messages=messages,  # type: ignore
                    tools=tools,  # type: ignore
                    tool_choice=cast(ChatCompletionToolChoiceOptionParam, tool_choice),
                    temperature=(
                        temperature if self.name.startswith("o1") else NOT_GIVEN
                    ),
                    response_format=cast(ResponseFormat, {"type": response_format}),
                    max_tokens=(
                        self.max_output_token
                        if not self.name.startswith("o1")
                        else NOT_GIVEN
                    ),
                    max_completion_tokens=(
                        self.max_output_token
                        if self.name.startswith("o1")
                        else NOT_GIVEN
                    ),
                    top_p=top_p,
                    stream=False,
                )
            else:
                response: ChatCompletion = self.client.chat.completions.create(
                    model=self.name,
                    messages=messages,  # type: ignore
                    tools=tools if tools is not None else NOT_GIVEN,  # type: ignore
                    temperature=(
                        temperature if self.name.startswith("o1") else NOT_GIVEN
                    ),
                    response_format=cast(ResponseFormat, {"type": response_format}),
                    max_tokens=(
                        self.max_output_token
                        if not self.name.startswith("o1")
                        else NOT_GIVEN
                    ),
                    max_completion_tokens=(
                        self.max_output_token
                        if self.name.startswith("o1")
                        else NOT_GIVEN
                    ),
                    top_p=top_p,
                    stream=False,
                )

            usage_stats = response.usage
            assert usage_stats is not None

            input_tokens = int(usage_stats.prompt_tokens)
            output_tokens = int(usage_stats.completion_tokens)
            cost = self.calc_cost(input_tokens, output_tokens)

            common.thread_cost.process_cost += cost
            common.thread_cost.process_input_tokens += input_tokens
            common.thread_cost.process_output_tokens += output_tokens

            raw_response = response.choices[0].message
            # log_and_print(f"Raw model response: {raw_response}")
            content = self.extract_resp_content(raw_response)
            raw_tool_calls = raw_response.tool_calls
            func_call_intents = self.extract_resp_func_calls(raw_response)
            return (
                content,
                raw_tool_calls,
                func_call_intents,
                cost,
                input_tokens,
                output_tokens,
            )
        except BadRequestError as e:
            logger.debug("BadRequestError ({}): messages={}", e.code, messages)
            if e.code == "context_length_exceeded":
                log_and_print("Context length exceeded")
            raise e


class Gpt_o1mini(OpenaiModel):
    def __init__(self):
        super().__init__("o1-mini", 8192, 0.000003, 0.000012, parallel_tool_call=True)
        self.note = "Mini version of state of the art. Up to Oct 2023."

    # FIXME: the returned type contains OpenAI specific Types, which should be avoided
    @retry(wait=wait_random_exponential(min=30, max=600), stop=stop_after_attempt(3))
    def call(
        self,
        messages: list[dict],
        top_p: float = 1,
        tools: list[dict] | None = None,
        response_format: Literal["text", "json_object"] = "text",
        temperature: float | None = None,
        reasoning_effort: Literal["low", "medium", "high"] | NotGiven = "medium",
        **kwargs,
    ) -> tuple[
        str,
        list[ChatCompletionMessageToolCall] | None,
        list[FunctionCallIntent],
        float,
        int,
        int,
    ]:
        # if response_format == "json_object":
        #     last_content = messages[-1]["content"]
        #     last_content += "\nYour response MUST start with { and end with }. DO NOT write anything else other than the json. Ignore writing triple-backticks."
        #     messages[-1]["content"] = last_content
        #     response_format = "text"

        # for msg in messages:
        #     msg["role"] = "user"
        return super().call(
            messages,
            top_p,
            tools,
            response_format,
            NOT_GIVEN,
            reasoning_effort=reasoning_effort,
            **kwargs,
        )


class Gpt_o1(OpenaiModel):
    def __init__(self):
        super().__init__(
            "o1-2024-12-17", 8192, 0.000003, 0.000012, parallel_tool_call=True
        )
        self.note = "State of the art reasoning model. Up to Oct 2023."

    # FIXME: the returned type contains OpenAI specific Types, which should be avoided
    @retry(wait=wait_random_exponential(min=30, max=600), stop=stop_after_attempt(3))
    def call(
        self,
        messages: list[dict],
        top_p: float = 1,
        tools: list[dict] | None = None,
        response_format: Literal["text", "json_object"] = "text",
        temperature: float | None = None,
        reasoning_effort: Literal["low", "medium", "high"] | NotGiven = "high",
        **kwargs,
    ) -> tuple[
        str,
        list[ChatCompletionMessageToolCall] | None,
        list[FunctionCallIntent],
        float,
        int,
        int,
    ]:
        # if response_format == "json_object":
        #     last_content = messages[-1]["content"]
        #     last_content += "\nYour response MUST start with { and end with }. DO NOT write anything else other than the json. Ignore writing triple-backticks."
        #     messages[-1]["content"] = last_content
        #     response_format = "text"

        # for msg in messages:
        #     msg["role"] = "user"
        return super().call(
            messages,
            top_p,
            tools,
            response_format,
            NOT_GIVEN,
            reasoning_effort=reasoning_effort,
            **kwargs,
        )

class Gpt4_1_mini(OpenaiModel):
    def __init__(self):
        # Use the Azure deployment name instead of model name
        super().__init__("gpt-4.1-mini", 16384, 0.0000025, 0.000010, parallel_tool_call=True)
        self.note = "Azure custom deployment: gpt-4.1-mini"

class Gpt4o_20240806(OpenaiModel):
    def __init__(self):
        super().__init__(
            "gpt-4o-2024-08-06", 16384, 0.0000025, 0.000010, parallel_tool_call=True
        )
        self.note = "Multimodal model. Up to Apr 2023."


class Gpt4o_20240513(OpenaiModel):
    def __init__(self):
        super().__init__(
            "gpt-4o-2024-05-13", 4096, 0.000005, 0.000015, parallel_tool_call=True
        )
        self.note = "Multimodal model. Up to Oct 2023."


class Gpt4_Turbo20240409(OpenaiModel):
    def __init__(self):
        super().__init__(
            "gpt-4-turbo-2024-04-09", 4096, 0.00001, 0.00003, parallel_tool_call=True
        )
        self.note = "Turbo with vision. Up to Dec 2023."


class Gpt4_0125Preview(OpenaiModel):
    def __init__(self):
        super().__init__(
            "gpt-4-0125-preview", 4096, 0.00001, 0.00003, parallel_tool_call=True
        )
        self.note = "Turbo. Up to Dec 2023."


class Gpt4_1106Preview(OpenaiModel):
    def __init__(self):
        super().__init__(
            "gpt-4-1106-preview", 4096, 0.00001, 0.00003, parallel_tool_call=True
        )
        self.note = "Turbo. Up to Apr 2023."


class Gpt35_Turbo0125(OpenaiModel):
    # cheapest gpt model
    def __init__(self):
        super().__init__(
            "gpt-3.5-turbo-0125", 1024, 0.0000005, 0.0000015, parallel_tool_call=True
        )
        self.note = "Turbo. Up to Sep 2021."


class Gpt35_Turbo1106(OpenaiModel):
    def __init__(self):
        super().__init__(
            "gpt-3.5-turbo-1106", 1024, 0.000001, 0.000002, parallel_tool_call=True
        )
        self.note = "Turbo. Up to Sep 2021."


class Gpt35_Turbo16k_0613(OpenaiModel):
    def __init__(self):
        super().__init__("gpt-3.5-turbo-16k-0613", 1024, 0.000003, 0.000004)
        self.note = "Turbo. Deprecated. Up to Sep 2021."


class Gpt35_Turbo0613(OpenaiModel):
    def __init__(self):
        super().__init__("gpt-3.5-turbo-0613", 512, 0.0000015, 0.000002)
        self.note = "Turbo. Deprecated. Only 4k window. Up to Sep 2021."


class Gpt4_0613(OpenaiModel):
    def __init__(self):
        super().__init__("gpt-4-0613", 512, 0.00003, 0.00006)
        self.note = "Not turbo. Up to Sep 2021."


class Gpt4o_mini_20240718(OpenaiModel):
    def __init__(self):
        super().__init__("gpt-4o-mini-2024-07-18", 4096, 0.00000015, 0.0000006)


class DeepSeekV3(Model):
    """
    DeepSeek V3 model using Azure AI Inference
    """
    
    _instances = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
            cls._instances[cls]._initialized = False
        return cls._instances[cls]

    def __init__(self):
        if self._initialized:
            return
        super().__init__(
            "DeepSeek-V3-0324", 
            cost_per_input=0.0000014,  # Estimated cost per input token
            cost_per_output=0.0000028,  # Estimated cost per output token
            parallel_tool_call=False
        )
        self.max_output_token = 4096
        self.client = None
        self.endpoint = "https://omaralexguzmanm21-7613-resource.services.ai.azure.com/models"
        self.model_name = "DeepSeek-V3-0324"
        self.note = "DeepSeek V3 via Azure AI Inference"
        self._initialized = True

    def setup(self) -> None:
        """Initialize Azure AI Inference client for DeepSeek"""
        if not AZURE_AI_AVAILABLE:
            print("Azure AI Inference package not available. Please install: pip install azure-ai-inference")
            sys.exit(1)
            
        if self.client is None:
            api_key = self.check_api_key()
            self.client = ChatCompletionsClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(api_key),
                api_version="2024-05-01-preview"
            )

    def check_api_key(self) -> str:
        """Check for Azure AI API key"""
        key = os.getenv("AZURE_AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            print("Please set the AZURE_AI_API_KEY or OPENAI_API_KEY env var for DeepSeek")
            sys.exit(1)
        return key

    def _convert_messages(self, messages: list[dict]) -> list:
        """Convert OpenAI format messages to Azure AI format"""
        azure_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                azure_messages.append(SystemMessage(content=content))
            elif role == "user":
                azure_messages.append(UserMessage(content=content))
            elif role == "assistant":
                azure_messages.append(AssistantMessage(content=content))
        
        return azure_messages

    @retry(wait=wait_random_exponential(min=30, max=600), stop=stop_after_attempt(3))
    def call(
        self,
        messages: list[dict],
        top_p: float = 1,
        tools: list[dict] | None = None,
        response_format: Literal["text", "json_object"] = "text",
        temperature: float | None = None,
        **kwargs,
    ) -> tuple[
        str,
        list[ChatCompletionMessageToolCall] | None,
        list[FunctionCallIntent],
        float,
        int,
        int,
    ]:
        """
        Call DeepSeek V3 via Azure AI Inference with enhanced rate limit handling
        """
        if temperature is None:
            temperature = common.MODEL_TEMP

        assert self.client is not None
        
        try:
            # Convert messages to Azure AI format
            azure_messages = self._convert_messages(messages)
            
            # Make API call with rate limit handling
            response = self.client.complete(
                messages=azure_messages,
                max_tokens=self.max_output_token,
                temperature=temperature,
                top_p=top_p,
                presence_penalty=0.0,
                frequency_penalty=0.0,
                model=self.model_name
            )
            
            # Extract response content
            content = response.choices[0].message.content or ""
            
            # Calculate costs (estimated based on input/output tokens)
            # Note: Azure AI Inference might not provide exact token counts
            input_tokens = sum(len(msg.get("content", "").split()) for msg in messages) * 1.3  # Rough estimate
            output_tokens = len(content.split()) * 1.3  # Rough estimate
            cost = self.calc_cost(int(input_tokens), int(output_tokens))
            
            # Update thread costs
            common.thread_cost.process_cost += cost
            common.thread_cost.process_input_tokens += int(input_tokens)
            common.thread_cost.process_output_tokens += int(output_tokens)
            
            # Return in expected format (no tool calls for now)
            return (
                content,
                None,  # raw_tool_calls
                [],    # func_call_intents
                cost,
                int(input_tokens),
                int(output_tokens),
            )
            
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                logger.warning(f"DeepSeek rate limit hit, will retry with backoff: {e}")
                # Sleep additional time for rate limits beyond tenacity retry
                import time
                time.sleep(60)  # Wait 1 minute extra for rate limits
            logger.error(f"DeepSeek API error: {e}")
            raise e
