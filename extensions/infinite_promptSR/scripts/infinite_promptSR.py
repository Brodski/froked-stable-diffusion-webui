from dataclasses import dataclass
from copy import copy
import gradio as gr  # type: ignore
from modules import scripts
from modules import shared
from typing import List

from modules.shared import opts, state
from modules.processing import process_images, Processed, StableDiffusionProcessingTxt2Img
from modules.processing import fix_seed
from modules import devices
from scripts.xyz_grid import csv_string_to_list_strip


shared.options_templates.update(shared.options_section(('infinite_promptSR', 'Infinite Prompt S/R'), {
    'infinite_promptSR_num_entries': shared.OptionInfo(
        2, 'Number of Prompt S/R inputs',
        gr.Number, {'minimum': 1, 'maximum': 100, 'precision': 0}
    ),
}))

class ProcessedResultBski:
    def __init__(self):
        self.images: List = []
        self.all_prompts: List = []
        self.all_seeds: List = []
        self.infotexts: List = []
        self.index_of_first_image: int = 0
        self.promptSR_blocks_ui = []

class PromptSR_Block:
    def __init__(self):
        self.sr_arr: List[str] = [] # eg [big, medium, tiny]
        self.sr_neg_arr: List[str] = []


class Script(scripts.Script):
    def __init__(self):
        super().__init__()
        self.recent_images = []
        self.num_entries: int = shared.opts.infinite_promptSR_num_entries
        self.textboxes: List[str] = []  # Keep references to textboxes
        self.mega_prompt_arr = None
        self.mega_prompt_neg_arr = None
        self.processed_results_bski = None

    def title(self):
        return "Prompt Adder"
    
    def show(self, is_img2img):
        return True # scripts.AlwaysVisible ==> Show always in the UI

    
    def ui(self, is_img2img):
        self.promptSR_blocks_ui = [] # hold fields per PromptSR-block

        print("\n\n ***** INFINIT UI RELOADED ***** \n\n")
        print("promptSR_blocks_ui:", self.promptSR_blocks_ui)

        num_entries: int = shared.opts.infinite_promptSR_num_entries

        with gr.Blocks(analytics_enabled=False) as block:
            # https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/features#prompt-sr
            msg1 = "'Main prompt SR' and 'negative prompt SR' work simulanteously."
            msg2 = "They should be balanced (equal number of replace operation), extra entries will be ignored. Leaving it empty will not cause issues."
            msg3 = ""
            link = "https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/features#prompt-sr"
            link_msg = "Prompt SR same as 'XYZ Prompt SR'"
            info1 = gr.HTML(f"<p style=\"margin-bottom:0.75em\">{msg1}</p>")
            info2 = gr.HTML(f"<p style=\"margin-bottom:0.75em\">{msg2}</p>")
            info3 = gr.HTML(f"<a style=\"margin-bottom:0.75em\" href={link}>{link_msg}</a>")

            for i in range(1, num_entries + 1):
                with gr.Accordion(f"Prompt Adder {i}", open=False):
                    with gr.Row():
                        prompt = gr.Textbox(
                            label=f"Prompt S/R {i}",
                            placeholder="Main prompt SR (positive)",
                            lines=2
                        )        
                        neg_prompt = gr.Textbox(
                            label=f"Negative Prompt SR {i}",
                            placeholder="...",
                            lines=2
                        )
                        # have to do this b/c how they wrote it.
                        self.promptSR_blocks_ui.append(prompt)  # store reference, tuples
                        self.promptSR_blocks_ui.append(neg_prompt) 

        # MUST RETURN SHITTY GRADIO UI COMPONENTS!
        return [*self.promptSR_blocks_ui]
        # return [extra_text]

    # A111 Hook / framework thing (they call my code)
    # def before_process(self, p, extra_text):
    #     print("⭐ BEFORE")
    #     print("⭐ BEFORE")
    #     print("⭐ BEFORE")
    #     print("⭐ BEFORE")
    #     print("⭐ BEFORE")
    #     print("⭐ BEFORE")
    #     # If there's text in the box, add it to the prompt
    #     if extra_text and extra_text.strip():
    #         p.prompt = f"{p.prompt}, {extra_text}"
    #         print(f"Added to prompt: {extra_text}")

    def make_an_image(self, p: Processed) -> Processed:
        if shared.state.interrupted or state.stopping_generation:
            return Processed(p, [], p.seed, "")
        
        p_copy = copy(p)
        p_copy.styles = p_copy.styles[:]
        
        p_copy.seed += 1 # TODO, idk wtf is actually hapneing here

        try:
            res = process_images(p_copy)
        except Exception as e:
            errors.display(e, "generating image for xyz plot")
            res = Processed(p, [], p.seed, "")

        return res
        

    def wrangle_data(self, sr_prompt, sr_negative):
        pass
    
    def truncate_excessive(self, promptSR_block: List[PromptSR_Block]):
        for sr_b in promptSR_block:
            num_operations = self.count_operations_level_1(sr_b.sr_arr, sr_b.sr_neg_arr)
            sr_b.sr_arr     = sr_b.sr_arr[:num_operations]
            sr_b.sr_neg_arr = sr_b.sr_neg_arr[:num_operations]
            # cut off excessive prompts
            

    # stupid copy paste code, i know, i lazy.
    def estimate_job_count_UI(self, promptSR_blocks_ui, MINI_BLOCK_LENGTH):
        total_operations_counters = 0 
        for idx in range(0, len(promptSR_blocks_ui), MINI_BLOCK_LENGTH): 
            sr_prompt = promptSR_blocks_ui[idx]
            sr_neg_prompt = promptSR_blocks_ui[idx + 1]

            sr_arr: List[str] = csv_string_to_list_strip(sr_prompt)
            sr_neg_arr: List[str] = csv_string_to_list_strip(sr_neg_prompt)
            
            num_operations = self.count_operations_level_1(sr_arr, sr_neg_arr)
            total_operations_counters = total_operations_counters * num_operations
        return total_operations_counters

    
    def count_operations_level_1(self, sr_arr: List[str], sr_neg_arr: List[str]):
        sr_count = len(sr_arr) if len(sr_arr) > 0 else float('inf')
        sr_neg_count = len(sr_neg_arr) if len(sr_neg_arr) > 0 else float('inf')

        replace_operations_at_this_level = min(sr_neg_count, sr_count) if (min(sr_neg_count, sr_count) != float('inf')) else 0
        
        # print("-- infitit | sr_arr", sr_arr)
        # print("-- infitit | sr_neg_arr", sr_neg_arr)
        # print("-- infitit | sr_count", sr_count)
        # print("-- infitit | sr_neg_count", sr_neg_count)
        # print("-- infitit | replace_operations_at_this_level", replace_operations_at_this_level)
        return replace_operations_at_this_level

    # code sorta copied from "xyz_grid.py @ apply_prompt()"
    def replace_that(self, p: Processed, indexs, old_replace, new_replace, prompt, prompt_neg, lazy_id): 
        idx, j = indexs

        print("    % OLD", old_replace, " ---> NEW:", new_replace)
        print("    % OLD", old_replace, " ---> NEW:", new_replace)
        print("    % OLD", old_replace, " ---> NEW:", new_replace)
        if old_replace not in prompt and old_replace not in prompt_neg:
            print("old_replace=", old_replace)
            print("p.prompt=",  p.prompt.replace("\n", " "))
            raise RuntimeError(f"Prompt S/R did not find {old_replace} in prompt or negative prompt.")
        
        # temp_prompt = self.mega_prompt_arr[idx][k]
        # temp_neg_prompt = self.mega_prompt_neg_arr[idx][k]


        if lazy_id == "is_prompt":
            prompt = prompt.replace(old_replace, new_replace)
            p.prompt = prompt
            self.mega_prompt_arr[idx][j] = prompt
            # p.prompt = p.prompt.replace(old_replace, new_replace)
        if lazy_id == "is_neg_prompt":
            prompt_neg = prompt_neg.replace(old_replace, new_replace)
            p.negative_prompt = prompt_neg
            self.mega_prompt_neg_arr[idx][j] = prompt_neg
            # p.negative_prompt = p.negative_prompt.replace(old_replace, new_replace)
            
        # BOOM
        return prompt, prompt_neg

    def replace_infinit_sr2(self, p: Processed, idx_, promptSR_block_arr: List[PromptSR_Block], prompt: str, prompt_neg: str):
        # fyi: promptSR_block_arr = [prompt_sr1, prompt_sr2, prompt_sr3, ...]
        # fyi: prompt_sr          = sr, sr_neg 
        # fyi: sr, sr_neg         = [big, small, tiny], [outside, inside, city]
        for k, promptSR_input in enumerate(promptSR_block_arr):
            promptSR_block: PromptSR_Block = promptSR_input
            num_replaces_todo = max(len(promptSR_block.sr_arr), len(promptSR_block.sr_neg_arr))

            prompt_queue = []
            for j in range(0, num_replaces_todo):
                
                print("    # # # # # # # # # # # # # # # # # # # # # # # # ")
                print(f"    # ({idx_}, {j}) # ")
                print("    # prompt: " + prompt.replace('\n', ''))
                tuplez = (idx_, j)
                if j > 0: # skip first entry
                    if promptSR_block.sr_arr: #not empty
                        prompt, prompt_neg = self.replace_that(p, (idx_, j), promptSR_block.sr_arr[j-1], promptSR_block.sr_arr[j], prompt, prompt_neg, "is_prompt")
                    if promptSR_block.sr_neg_arr:
                        prompt, prompt_neg = self.replace_that(p, (idx_, j), promptSR_block.sr_neg_arr[j-1], promptSR_block.sr_neg_arr[j],  prompt, prompt_neg,"is_neg_prompt")
                prompt_queue.append([str(prompt), str(prompt_neg)])

                tricky_lazy_seed_counter = 1
                p.seed = p.seed + tricky_lazy_seed_counter if p.seed != -1 else p.seed # this is not a accurate counter, but it does increment
                # print(f"  !!!{() * (k+1)} out of {total_operations_counters}")
                state.job = f"{(1) * (j+1)} out of {69}"
                processed: Processed = self.make_an_image(p)


                # idk why i made this a loop, but i guess i'm keeping it
                for i, img in enumerate(processed.images):
                    # print("    infinite| i, img:", i, img)
                    self.processed_results_bski.images.append(img)
                    self.processed_results_bski.all_prompts.append(processed.prompt)
                    self.processed_results_bski.all_seeds.append(processed.seed)
                    self.processed_results_bski.infotexts.append(processed.infotexts[0])

            # after we replace all for current 
            print("    ********************************* ")
            print("    * COMPLETED ROUND ", idx_)
            ass = 0
            for prompttt_ in prompt_queue:
                pmt = prompttt_[0]
                print("    * prompt", ass, ": ", pmt.replace("\n", " "))
                ass = ass + 1
            cnt = 0
            for ppp in promptSR_block_arr[1:]:
                print("    ** ", cnt, ": ", ppp)
                cnt = cnt + 1
                
            for prompttt_ in prompt_queue:
                pmt = prompttt_[0]
                pmt_neg = prompttt_[1]
                self.replace_infinit_sr2(p, idx_+1, promptSR_block_arr[1:], pmt, pmt_neg)
        return

    # def replace_infinit_sr(self, p: Processed, idx_, promptSR_block_arr: List[PromptSR_Block], prompt: str, prompt_neg: str):
    # #     # fyi: promptSR_block_arr = [prompt_sr1, prompt_sr2, prompt_sr3, ...]
    # #     # fyi: prompt_sr          = sr, sr_neg 
    # #     # fyi: sr, sr_neg         = [big, small, tiny], [outside, inside, city]
    #     for k, promptSR_input in enumerate(promptSR_block_arr):
    #         length = max(len(promptSR_input.sr_arr), len(promptSR_input.sr_neg_arr))
    #         for j in range(0,length):
    #             if j > 0: # skip first entry
    #                 if promptSR_input.sr_arr: #not empty
    #                     self.replace_that(p, (idx_, j), promptSR_input.sr_arr[j-1], promptSR_input.sr_arr[j], "is_prompt")
    #                 if promptSR_input.sr_neg_arr:
    #                     self.replace_that(p, (idx_, j), promptSR_input.sr_neg_arr[j-1], promptSR_input.sr_neg_arr[j], "is_neg_prompt")

    #             tricky_lazy_seed_counter = 1
    #             p.seed = p.seed + tricky_lazy_seed_counter if p.seed != -1 else p.seed # this is not a accurate counter, but it does increment
    #             # print(f"  !!!{() * (k+1)} out of {total_operations_counters}")
    #             state.job = f"{(1) * (k+1)} out of {69}"
    #             processed: Processed = self.make_an_image(p)

    #             # idk why i made this a loop, but i guess i'm keeping it
    #             for i, img in enumerate(processed.images):
    #                 # print("    infinite| i, img:", i, img)
    #                 self.processed_results_bski.images.append(img)
    #                 self.processed_results_bski.all_prompts.append(processed.prompt)
    #                 self.processed_results_bski.all_seeds.append(processed.seed)
    #                 self.processed_results_bski.infotexts.append(processed.infotexts[0])

    #     # after we replace all for current 
    #     self.replace_infinit_sr(p, idx_+1, promptSR_block[1:])
    #     return


    # A111 Hook
    def run(self, p: Processed, *promptSR_blocks_ui):
        devices.torch_gc()        

        self.processed_results_bski = ProcessedResultBski()
        fix_seed(p)

        # IMPORTANT 
        # ---> Must update this per component in the accordion @ UI. (idk if there exists a smart way, but i lazy)
        MINI_BLOCK_LENGTH = 2 # ["positive prompt" + "negative"]


        total_operations_counters = self.estimate_job_count_UI(promptSR_blocks_ui, MINI_BLOCK_LENGTH)
        state.job_count = total_operations_counters * p.n_iter * p.multiple_run_count

        print(" | | | | |  IT'S GO TIME  | | | | |")
        print(" | | | | |  IT'S GO TIME  | | | | |")
        print(" | | | | |  IT'S GO TIME  | | | | |")
        print("    infinit |total_operations_counters", total_operations_counters)
        print("    infinit |state.job_count", state.job_count)

        # create bski_promptz
        promptSR_block_arr: List[PromptSR_Block] = []
        for idx in range(0, len(promptSR_blocks_ui), MINI_BLOCK_LENGTH): # auto1111 gradio thing is stupid, prob have to do this b/c `def ui()` must return gradio components
            print("(bigloop)   idx:", idx)
            sr_prompt = promptSR_blocks_ui[idx]
            sr_neg_prompt = promptSR_blocks_ui[idx + 1]

            sr_arr: List[str] = csv_string_to_list_strip(sr_prompt)
            sr_neg_arr: List[str] = csv_string_to_list_strip(sr_neg_prompt)
            
            promptSR_block = PromptSR_Block()
            promptSR_block.sr_arr = sr_arr
            promptSR_block.sr_neg_arr = sr_neg_arr
            promptSR_block_arr.append(promptSR_block)

        # Boom 1
        self.truncate_excessive(promptSR_block_arr)

        # Boom 2
        # initialize all the prompts with the OG prompt
        self.mega_prompt_arr: List[List[str]] = [] # [ [x's] [y's] [z's] ... [] ] x,y,z = array of promptSRs
        self.mega_prompt_neg_arr: List[List[str]] = [] 
        for _promptSR in promptSR_block_arr: # TYPE = BSKI
            length = max(len(_promptSR.sr_arr), len(_promptSR.sr_neg_arr))
            temp_arr = []
            temp_neg_arr = []
            for _ in range(0, length):
                temp_arr.append(str(p.prompt)) # str() should prevent shared reference. idk if redundant but im doing it.
                temp_neg_arr.append(str(p.negative_prompt)) 
            self.mega_prompt_arr.append(temp_arr)
            self.mega_prompt_neg_arr.append(temp_neg_arr)
        #debug print
        for i, pmt in enumerate(self.mega_prompt_arr):
            print(i)
            for k,pp in enumerate(pmt):
                print(f"    {k}: ")


        # Boom 3
        self.replace_infinit_sr2(p, 0, promptSR_block_arr, str(p.prompt), str(p.negative_prompt))


        if not any(self.processed_results_bski.images):
            print("Unexpected error: infinite prompt s/r failed to return even a single processed image")
            return Processed(p, [])
            

