from dataclasses import dataclass
from copy import copy
import gradio as gr  # type: ignore
from modules import scripts
from modules import shared
from typing import List
from enum import Enum, auto

from modules.shared import opts, state
from modules.processing import process_images, Processed, fix_seed
from modules import devices, errors, bski_split_helper
from scripts.xyz_grid import csv_string_to_list_strip

from modules.processing import process_images, Processed, StableDiffusionProcessingTxt2Img


shared.options_templates.update(shared.options_section(('infinite_promptSR', 'Infinite Prompt S/R'), {
    'infinite_promptSR_num_entries': shared.OptionInfo(
        2, 'Number of Prompt S/R inputs',
        gr.Number, {'minimum': 1, 'maximum': 100, 'precision': 0}
    ),
}))

class ProcessedResultBski:
    def __init__(self):
        self._processed: Processed = None
        self.images: List = []
        self.all_prompts: List = []
        self.all_seeds: List = []
        self.infotexts: List = []
        self.index_of_first_image: int = 0
        self.promptSR_blocks_ui = []

    def __getattr__(self, name): # Pro move. I am the best
        return getattr(self._processed, name)

class To_Replace:
    def __init__(self):
        self.sr_arr: List[str] = [] # eg [big, medium, tiny]
        self.sr_neg_arr: List[str] = []
        self.is_enabled: bool = False

class Prompt:
    def __init__(self):
        self.main: str = ""     # "a cool outspace landscape with space dinosaurs and space pirates"
        self.negative: str = "" # "low res, worst, 6 fingers"

class Grid_Type(Enum):
    TREE_FUNK = "tree_funk" # auto()
    COLLAPSE_INJECT = "collapse_inject"
    COOL_HORIZONTAL = "cool_horizontal"

class Seed_Type(Enum):
    FIXED_SEED = "fixed_seed" 
    INCREMENT_CONTINUOUSLY_SEED = "increment_continuously_seed"


class Script(scripts.Script):
    def __init__(self):
        super().__init__()
        self.recent_images = []
        self.num_entries: int = shared.opts.infinite_promptSR_num_entries
        self.processed_results_bski = None

    def title(self):
        return "Infinite Prompt S/R"
    
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
            msg3 = "NOTE: Increase number of prompt S/R's at: Settings ⟶ (Uncategorized) ⟶ Infinite Prompt S/R"
            msg4 = ""
            link = "https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/features#prompt-sr"
            link_msg = "Same functionality as 'XYZ Grid - Prompt SR'"
            # Grid display
            radio_grid_1 = Grid_Type.TREE_FUNK.value
            radio_grid_2 = Grid_Type.COLLAPSE_INJECT.value
            radio_grid_3 = Grid_Type.COOL_HORIZONTAL.value
            # Seed 
            radio_seed_1 = Seed_Type.FIXED_SEED.value
            radio_seed_2 = Seed_Type.INCREMENT_CONTINUOUSLY_SEED.value

            with gr.Row():
                radio_grid = gr.Radio([radio_grid_1, radio_grid_2, radio_grid_3], value=radio_grid_3, label="Grid display type")
                slider = gr.Slider(minimum=1, maximum=10, step=1, value=3, label="columnz_width")
            with gr.Row():
                radio_seed = gr.Radio([radio_seed_1, radio_seed_2], value=radio_seed_2, label="Seed behavior. (fixed_seed good for testing, increment_continuously_seed good for varying content, i.e. new seed always")
            # info1 = gr.HTML(f"<p style=\"margin-bottom:0.75em\">{msg1}</p>")
            # info2 = gr.HTML(f"<p style=\"margin-bottom:0.75em\">{msg2}</p>")
            # info3 = gr.HTML(f"<a style=\"margin-bottom:0.75em\" href={link}>{link_msg}</a>")

            self.promptSR_blocks_ui.append(radio_grid)
            self.promptSR_blocks_ui.append(slider)
            self.promptSR_blocks_ui.append(radio_seed)
            gr.Markdown("#### Replace:")
            for i in range(1, num_entries + 1):
                with gr.Accordion(f"Prompt SR", open=True):
                    with gr.Row():
                        is_enabled = gr.Checkbox(label="Enable", value=False)
                    with gr.Row():
                        prompt = gr.Textbox(
                            label=f"Positive {i}",
                            placeholder='"red hair, blue shirt"\n"spiked hair, punk shirt, leather boots"\nect...' if i == 1 else "...",
                            lines=3
                        )        
                    with gr.Row():
                        neg_prompt = gr.Textbox(
                            label=f"Negative {i}",
                            placeholder="...",
                            lines=1
                        )
                    # have to do this b/c how they wrote it.
                    self.promptSR_blocks_ui.append(is_enabled)
                    self.promptSR_blocks_ui.append(prompt)  # store reference, tuples
                    self.promptSR_blocks_ui.append(neg_prompt) 

            with gr.Accordion(f"Info", open=False):
                gr.Markdown(f"""- {msg3}
                        - {msg1}
                        - {msg2}
                        - {link_msg}. Docs [[↗]]({link})""")
            # gr.Markdown(f"""## Info
            #             - {msg3}
            #             - {msg1}
            #             - {msg2}
            #             - {link_msg}. Docs [[↗]]({link})""")
            
        # MUST RETURN SHITTY GRADIO UI COMPONENTS!
        return [*self.promptSR_blocks_ui]

    def make_the_images(self, p: StableDiffusionProcessingTxt2Img) -> Processed:
        
        if shared.state.interrupted or state.stopping_generation:
            return Processed(p, [], p.seed, "")
        
        print('make image, pseed:', p.seed)
        p.do_not_save_grid = True #im putting it here, you like it or not.
        p_copy = copy(p)
        print('make image, p_copy.seed:', p_copy.seed)
        p_copy.styles = p_copy.styles[:]
        
        # p_copy.seed += 1 # TODO, idk wtf is actually hapneing here

        try:
            res = process_images(p_copy)
        except Exception as e:
            errors.display(e, "generating image for xyz plot")
            res = Processed(p, [], p.seed, "")

        return res

    def truncate_excessive(self, promptSR_block: List[To_Replace]):
        for sr_b in promptSR_block:
            num_operations = self.count_operations_level_1(sr_b.sr_arr, sr_b.sr_neg_arr)
            sr_b.sr_arr     = sr_b.sr_arr[:num_operations]
            sr_b.sr_neg_arr = sr_b.sr_neg_arr[:num_operations]
            # cut off excessive prompts

    def count_operations_level_1(self, sr_arr: List[str], sr_neg_arr: List[str]):
        sr_count = len(sr_arr) if len(sr_arr) > 0 else float('inf')
        sr_neg_count = len(sr_neg_arr) if len(sr_neg_arr) > 0 else float('inf')

        replace_operations_at_this_level = min(sr_neg_count, sr_count) if (min(sr_neg_count, sr_count) != float('inf')) else 0

        return replace_operations_at_this_level

    
    def gen_prompts(self, prompt: Prompt, replace_todos: To_Replace):
        new_promptz: List[Prompt] = []
        
        num_replaces_todo = max(len(replace_todos.sr_arr), len(replace_todos.sr_neg_arr))
        for i in range(0, num_replaces_todo):
            str_main, str_neg = None, None
            if i > 0: # skip the 1st one
                if replace_todos.sr_arr: #not empty
                    old = replace_todos.sr_arr[0]
                    new = replace_todos.sr_arr[i]
                    is_type = "is_prompt"
                    str_main, _ = self.replace_that_2(old, new,  prompt, is_type)
                if replace_todos.sr_neg_arr:
                    old = replace_todos.sr_neg_arr[0]
                    new = replace_todos.sr_neg_arr[i]
                    is_type = "is_neg_prompt"
                    _, str_neg = self.replace_that_2(old, new,  prompt, is_type)
            new_p = Prompt()
            new_p.main = str_main or prompt.main
            new_p.negative = str_neg or prompt.negative
            new_promptz.append(new_p)
        return new_promptz

    # code sorta copied from "xyz_grid.py @ apply_prompt()"
    def replace_that_2(self, old_replace, new_replace, prompt: Prompt, lazy_id) -> Prompt: 
        print("    % OLD", old_replace, " ---> NEW:", new_replace)
        print("    % OLD", old_replace, " ---> NEW:", new_replace)
        print("    % OLD", old_replace, " ---> NEW:", new_replace)

        if old_replace not in prompt.main and old_replace not in prompt.negative:
            print("|ERROR| old_replace=", old_replace)
            print("|ERROR| prompt.main=",  prompt.main.replace("\n", " "))
            raise RuntimeError(f"Prompt S/R did not find {old_replace} in prompt or negative prompt.")
        pmt = Prompt()
        pmt.main = prompt.main
        pmt.negative = prompt.negative
        if lazy_id == "is_prompt":
            pmt.main = prompt.main.replace(old_replace, new_replace)
        if lazy_id == "is_neg_prompt":
            pmt.negative = prompt.negative.replace(old_replace, new_replace)
            
        # BOOM
        return pmt.main, pmt.negative

    def cross_pollinate(self, init_prompts: List[Prompt], replaces_list: List[To_Replace]):
        print(" ------ cross_pollinate ----------")
        print(" ------ len(init_prompts): ", len(init_prompts))
        for x in replaces_list:
            print(" ------ replace: ", x.sr_arr)
        more_prompts: List[Prompt] = []
        if not replaces_list:
            return init_prompts
        
        for i,prompt in enumerate(init_prompts):
            print(" ------ ", i)
            tmp_p: List[Prompt] = self.gen_prompts(prompt, replaces_list[0])
            more_prompts = more_prompts + tmp_p

        all_of_dat = self.cross_pollinate(more_prompts, replaces_list[1:])
        return  all_of_dat


    def cross_pollinate_horizontal(self, init_prompts: List[Prompt], replaces_list: List[To_Replace]):
        print(" ------ cross_pollinate ----------")
        print(" ------ len(init_prompts): ", len(init_prompts))
        for x in replaces_list:
            print(" ------ replace: ", x.sr_arr)
        more_prompts: List[Prompt] = []
        more_prompts_extra_list: List[List[Prompt]] = [] #will be same lenght of init_prompts
        if not replaces_list:
            return init_prompts
        
        for i,prompt in enumerate(init_prompts):
            print(" ------ ", i)
            generated_prompts: List[Prompt] = self.gen_prompts(prompt, replaces_list[0])
            more_prompts_extra_list.append(generated_prompts)

        num_replaces_todo = max(len(replaces_list[0].sr_arr), len(replaces_list[0].sr_neg_arr))
        for i in range(0, num_replaces_todo):
            for k, prompt__ in enumerate(init_prompts):            
                print(f"(i,k) ({i},{k})")
                more_prompts.append(more_prompts_extra_list[k][i])


        all_of_dat = self.cross_pollinate_horizontal(more_prompts, replaces_list[1:])

        return  all_of_dat
    
    def replace_infinit_sr(self, idx_, init_prompts: List[Prompt], to_replace_list: List[To_Replace]):
        # fyi: to_replace_list    = [prompt_sr1, prompt_sr2, prompt_sr3, ...]
        # fyi: prompt_sr          = sr, sr_neg 
        # fyi: sr, sr_neg         = [big, small, tiny], [outside, inside, city]
        if not to_replace_list:
            return init_prompts
        new_prompts = []

        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        to_replace: To_Replace = to_replace_list[0]
        num_replaces_todo = max(len(to_replace.sr_arr), len(to_replace.sr_neg_arr))

        for i, p__ in enumerate(init_prompts):
            print(f"    # {i} ---> init_prompts=", p__.main.replace('\n', "")[:66])
            
        for i, p__ in enumerate(init_prompts):
            print(f"******* GOING IN: {i} of {len(init_prompts)} *******")
            print(f"******* GOING IN: {i} of {len(init_prompts)} *******")
            print(f"******* GOING IN: {i} of {len(init_prompts)} *******")
            previous_prompt = None # We have to reset, and set to None
            for j in range(0, num_replaces_todo):
                print("\n    # # # # # # # # # # # # # # # # # # # # # # # # ")
                print(f"    # ({idx_}, {j}) # ")
                print(f"    # len(init_prompts):", len(init_prompts))
                print(f"    # {i} ---> init_prompts=", p__.main.replace('\n', "")[:126])
                prp__ = previous_prompt or p__
                str_main, str_neg = None, None
                if j == 0: # skip first entry
                    print(" --- SKIP --- ")
                    continue
                if to_replace.sr_arr: #not empty
                    old = to_replace.sr_arr[j-1] if to_replace.sr_arr else None
                    new = to_replace.sr_arr[j]
                    str_main, _ = self.replace_that_2(old, new, prp__, "is_prompt")

                if to_replace.sr_neg_arr:
                    old = to_replace.sr_neg_arr[j-1] if to_replace.sr_neg_arr else None
                    new = to_replace.sr_neg_arr[j]
                    _, str_neg = self.replace_that_2(old, new, prp__,"is_neg_prompt")

                prompt__ = Prompt()
                prompt__.main = str_main or prp__.main
                prompt__.negative = str_neg or prp__.negative
                new_prompts.append(prompt__)
                previous_prompt = prompt__


        # BOOM 
        init_prompts.extend(new_prompts)

        # after we replace all for current 
        print("********************************** ")
        print("** COMPLETED ROUND ", idx_)
        ass = 0
        for prompttt_ in init_prompts:
            pmt = prompttt_.main
            print(" $$$$ init_prompts", ass, ": ", pmt.replace("\n", " ")[:66])
            ass = ass + 1
        cnt = 0
        for ppp in to_replace_list[1:]:
            print(" $$$$ BLOCK ", cnt, ": ", ppp.sr_arr)
            cnt = cnt + 1

        return self.replace_infinit_sr(idx_+1, init_prompts, to_replace_list[1:])

    # A111 Hook
    def run(self, p: StableDiffusionProcessingTxt2Img, *promptSR_blocks_ui):
        devices.torch_gc()        
        print(" 🙀 BEFORE FIXED SEED:", p.seed)
        initial_seed = int(p.seed)
        if p.seed == -1:
            fix_seed(p)
        print(" 🙀 AFTER FIXED SEED:", p.seed)

        if p.columnz_width and p.columnz_width > 0:
            p.columnz_width = 0 # Avoid conflict w/ my custom code elsewhere

        # IMPORTANT 
        # ---> Must update this per component in the accordion @ UI. (idk if there exists a smart way, but i lazy)
        MINI_BLOCK_LENGTH = 3 # ["is_enabled" + "positive prompt" + "negative"]

        print(" | | | | |  IT'S GO TIME  | | | | |")
        print(" | | | | |  IT'S GO TIME  | | | | |")
        print(" | | | | |  IT'S GO TIME  | | | | |")
        print("    infinit |state.job_count", state.job_count)

        radio_grid_type  = promptSR_blocks_ui[0]
        slider_columnz_value = promptSR_blocks_ui[1]
        radio_seed_type = promptSR_blocks_ui[2]
        promptSR_blocks_ui = promptSR_blocks_ui[3:]


        # create bski_promptz
        replaces_list: List[To_Replace] = []
        for idx in range(0, len(promptSR_blocks_ui), MINI_BLOCK_LENGTH): # auto1111 gradio thing is stupid, prob have to do this b/c `def ui()` must return gradio components
            print("(bigloop)   idx:", idx)
            is_enabled_checkbox = promptSR_blocks_ui[idx]
            sr_prompt = promptSR_blocks_ui[idx + 1]
            sr_neg_prompt = promptSR_blocks_ui[idx + 2]

            sr_arr: List[str] = csv_string_to_list_strip(sr_prompt)
            sr_neg_arr: List[str] = csv_string_to_list_strip(sr_neg_prompt)
            if not sr_arr and not sr_arr:
                continue #empty cell for both
            if not is_enabled_checkbox:
                continue
            promptSR_block = To_Replace()
            promptSR_block.sr_arr = sr_arr
            promptSR_block.sr_neg_arr = sr_neg_arr
            replaces_list.append(promptSR_block)

        # Boom 1
        self.truncate_excessive(replaces_list)

        init_prompts = []
        t_prompt = Prompt()
        t_prompt.main = str(p.prompt)
        t_prompt.negative = str(p.negative_prompt)
        init_prompts.append(t_prompt)

        # ...boom
        total_items: int = p.multiple_run_count or 1
        total_items = total_items * p.n_iter # n_iter = batch_size. ...idk why they, a1111, do this
        for list in replaces_list:
            num_replaces_todo = max(len(list.sr_arr), len(list.sr_neg_arr))
            total_items = total_items * num_replaces_todo
        state.job_count = total_items



        # TODO!!!!!
        # grid_type = Grid_Type.COOL_HORIZONTAL
        grid_type = radio_grid_type
        print(" @@@@@@@@@@@@ DEBUG @@@@@@@@@@@@ ")
        print(" @grid_type:", grid_type)
        print(" @slider_columnz_value", slider_columnz_value)
        print(" @p.multiple_run_count:", p.multiple_run_count)
        print(" @total_items:", total_items)
        print(" @")
        if grid_type == Grid_Type.TREE_FUNK.value:
            mega_all: List[Prompt] = self.replace_infinit_sr(0, init_prompts, replaces_list)
        if grid_type == Grid_Type.COLLAPSE_INJECT.value:
            mega_all: List[Prompt] = self.cross_pollinate(init_prompts, replaces_list)
        if grid_type == Grid_Type.COOL_HORIZONTAL.value:
            mega_all: List[Prompt] = self.cross_pollinate_horizontal(init_prompts, replaces_list)



        self.processed_results_bski = ProcessedResultBski()

        for i, mega in enumerate(mega_all):
            print(f" xxxxxxxxx {i} xxxxxxxxx ")
            print(f" xxxxxxxxx {i} xxxxxxxxx ")
            print(f" xxxxxxxxx {i} xxxxxxxxx \n")
            state.job = f"{i} out of {total_items}"
            print(mega.main.replace('\n', " "))

            p.prompt = mega.main
            p.negative_prompt = mega.negative

            bski_multi = p.multiple_run_count if p.multiple_run_count else 1
            lower = (i) * bski_multi * p.n_iter # p.n_iter = batch count
            upper = (i+1) * bski_multi * (p.n_iter) 
            multi_msg = f"(Infinite prompt S/R): {lower} to {upper} out of {total_items}"
            print(multi_msg)
            state.job = multi_msg

            

            

 
            # is_increment_seed_always = False
            # is_fix_seed = False 
            # A1111 will increment seed regardless when batch_size > 1 (which makes sense, b/c it would be exact same image otherwise)
            # SEEEEEEEED
            # if rng seed, then this will continously increment the seed
            if radio_seed_type ==  Seed_Type.INCREMENT_CONTINUOUSLY_SEED.value and i != 0:
                tricky_lazy_seed_counter = (p.n_iter) # A1111 does complex things with the seed, but seems like incrementing by batch_size/n_iter will do the trick
                print("⚠.....BEFORE p.seed:", p.seed)
                p.seed = p.seed + tricky_lazy_seed_counter if p.seed != -1 else p.seed # this is not a accurate counter, but it does increment
                # p.seed += 1
                print("⚠.....AFTER p.seed:", p.seed)
            if radio_seed_type ==  Seed_Type.FIXED_SEED.value:
                pass

            processed: Processed = self.make_the_images(p)
            self.processed_results_bski._processed = processed # not really ideal, but w/e, seems A1111 code is kinda goofy anyways

            # if len(processed.images) > 1:
            if len(processed.images) > p.n_iter:
                # when batch/n_iter > 1, make_the_images() will create the grid image 
                processed.images = processed.images[1:]

            for k, img in enumerate(processed.images):
                # print("    infinite| i, img:", i, img)
                self.processed_results_bski.images.append(img)
                self.processed_results_bski.all_prompts.append(processed.prompt)
                print(f" {i}, {k} →→→→→→→→ seed:", processed.seed)
                self.processed_results_bski.all_seeds.append(processed.seed)
                self.processed_results_bski.infotexts.append(processed.infotexts[0])
            
        if not self.processed_results_bski:
            # Should never happen, I've only seen it on one of four open tabs and it needed to refresh.
            print("Unexpected error: Processing could not begin, you may need to refresh the tab or restart the service.")
            return Processed(p, [])
        if not any(self.processed_results_bski.images):
            print("Unexpected error: infinite prompt s/r failed to return even a single processed image")
            return Processed(p, [])
        
        self.processed_results_bski = bski_split_helper.do_column_thing(self.processed_results_bski, slider_columnz_value, p.outpath_grids, opts.grid_format)
        return self.processed_results_bski
            

