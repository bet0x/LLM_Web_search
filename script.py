import time
import re
import concurrent.futures

import gradio as gr

import modules.shared as shared
from modules.text_generation import generate_reply_HF, generate_reply_custom
from .llm_web_search import search_duckduckgo, dict_list_to_pretty_str


params = {
    "display_name": "LLM Web Search",
    "is_tab": True,
    "enable": True,
    "show search replies": True,
    "top search replies per query": 5,
    "instant answers": True,
    "regular search results": True,
    "search command regex": "Search_web: \"(.*)\"",
    "default command regex": "Search_web: \"(.*)\""
}


def setup():
    """
    Is executed when the extension gets imported.
    :return:
    """
    pass


def ui():
    """
    Creates custom gradio elements when the UI is launched.
    :return:
    """
    def update_result_type_setting(choice: str):
        if choice == "Instant answers":
            params.update({"instant answers": True})
            params.update({"regular search results": False})
        elif choice == "Regular results":
            params.update({"instant answers": False})
            params.update({"regular search results": True})
        else:
            params.update({"instant answers": True})
            params.update({"regular search results": True})

    def update_regex_setting(input_str: str):
        if input_str == "":
            params.update({"search command regex": params["default command regex"]})
            return {search_command_regex_error_label:
                        gr.HTML("", visible=False)}
        try:
            re.compile(input_str)
            params.update({"search command regex": input_str})
            return {search_command_regex_error_label:
                        gr.HTML("", visible=False)}
        except re.error as e:
            return {search_command_regex_error_label:
                        gr.HTML(f'<font color="red"> Invalid regex. {str(e).capitalize()}</font>', visible=True)}

    with gr.Row():
        enable = gr.Checkbox(value=params['enable'], label='Enable LLM web search')

    with gr.Row():
        result_radio = gr.Radio(
            ["Instant answers", "Regular results", "Both"],
            label="What kind of search results should be returned?",
            value="Both"
        )
        with gr.Column():
            search_command_regex = gr.Textbox(label="Search command regex string",
                                              placeholder=params["default command regex"])
            search_command_regex_error_label = gr.HTML("", visible=False)

    with gr.Accordion("Advanced settings", open=False):
        gr.Markdown("**Note: Changing these might result in DuckDuckGo rate limiting or the LLM being overwhelmed**")
        num_search_results = gr.Number(label="Max. search results per query", minimum=1, maximum=100, value=5)

    # Event functions to update the parameters in the backend
    enable.change(lambda x: params.update({"enable": x}), enable, None)
    num_search_results.change(lambda x: params.update({"top search replies per query": x}), num_search_results, None)
    result_radio.change(update_result_type_setting, result_radio, None)
    search_command_regex.change(update_regex_setting, search_command_regex, search_command_regex_error_label)


def custom_generate_reply(question, original_question, seed, state, stopping_strings, is_chat):
    """
    Overrides the main text generation function.
    :return:
    """
    if shared.model.__class__.__name__ in ['LlamaCppModel', 'RWKVModel', 'ExllamaModel', 'Exllamav2Model',
                                           'CtransformersModel']:
        generate_func = generate_reply_custom
    else:
        generate_func = generate_reply_HF

    if not params['enable']:
        for reply in generate_func(question, original_question, seed, state, stopping_strings, is_chat=is_chat):
            yield reply
        return

    web_search = False
    future_to_search_term = {}
    matched_patterns = {}
    max_search_results = params["top search replies per query"]
    search_command_regex = params["search command regex"]
    instant_answers = params["instant answers"]
    regular_search_results = params["regular search results"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for reply in generate_func(question, original_question, seed, state, stopping_strings, is_chat=is_chat):
            search_re_match = re.search(search_command_regex, reply)
            if search_re_match is not None:
                matched_pattern = search_re_match.group(0)
                if matched_patterns.get(matched_pattern):
                    continue
                web_search = True
                matched_patterns[matched_pattern] = True
                search_term = search_re_match.group(1)
                print(f"Searching for {search_term}...")
                future_to_search_term[executor.submit(search_duckduckgo,
                                                      search_term,
                                                      max_search_results,
                                                      instant_answers,
                                                      regular_search_results)] = search_term

            if re.search(search_command_regex, reply) is not None:
                yield reply
                break

            yield reply

        if web_search:
            reply += "\n```"
            reply += "\nSearch tool:\n"
            time.sleep(0.041666666666666664)
            yield reply
            search_result_str = ""
            for i, future in enumerate(concurrent.futures.as_completed(future_to_search_term)):
                search_term = future_to_search_term[future]
                try:
                    data = future.result()
                except Exception as exc:
                    exception_message = str(exc)
                    reply += f"The search tool encountered an error: {exception_message}"
                    print(f'{search_term} generated an exception: {exception_message}')
                else:
                    pretty_result = dict_list_to_pretty_str(data)
                    search_result_str += pretty_result
                    reply += pretty_result
                    yield reply
                    time.sleep(0.041666666666666664)
            print(f"search_result_str: {search_result_str}")
            if search_result_str == "":
                reply += f"The search tool encountered an error and did not return any results."
            reply += "```"
            yield reply


def output_modifier(string, state, is_chat=False):
    """
    Modifies the output string before it is presented in the UI. In chat mode,
    it is applied to the bot's reply. Otherwise, it is applied to the entire
    output.
    :param string:
    :param state:
    :param is_chat:
    :return:
    """
    return string


def custom_css():
    """
    Returns custom CSS as a string. It is applied whenever the web UI is loaded.
    :return:
    """
    return ''


def custom_js():
    """
    Returns custom javascript as a string. It is applied whenever the web UI is
    loaded.
    :return:
    """
    return ''


def chat_input_modifier(text, visible_text, state):
    """
    Modifies both the visible and internal inputs in chat mode. Can be used to
    hijack the chat input with custom content.
    :param text:
    :param visible_text:
    :param state:
    :return:
    """
    return text, visible_text


def state_modifier(state):
    """
    Modifies the dictionary containing the UI input parameters before it is
    used by the text generation functions.
    :param state:
    :return:
    """
    return state


def history_modifier(history):
    """
    Modifies the chat history before the text generation in chat mode begins.
    :param history:
    :return:
    """
    return history