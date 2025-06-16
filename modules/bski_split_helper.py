import math
from typing import List
from modules import processing, infotext_utils, images

class Bski_image_row_splitter:
    def __init__(self):
        self.imagez: List = []
        self.promptz: List = []
        self.seedz: List = []
        self.infotextz:List = []


def do_column_thing(processed, columnz_width, is_cool_split, outpath_grids, grid_format):
        rowz = math.ceil( len(processed.images) / columnz_width)
        print("bski - DOING COLUMN THING")
        grid = images.image_grid(processed.images, rows=rowz, columnz=columnz_width)
        processed.images.insert(0, grid)
        # print(processed)

        if not hasattr(processed, "bski_splitter"):
            processed.bski_splitter = Bski_image_row_splitter()

        # processed.bski_splitter = {
        #     "imagez": [],
        #     "promptz": [],
        #     "seedz": [],
        #     "infotextz": []
        # }
        if is_cool_split and columnz_width > 0:
            print("BSKI cool split")
            aux_processed_res_images = processed.images[1:] # we skip the first entry b/c its the super grid

            for i_ in range(rowz):
                # we get each row of images, (x images/columns long, then save it in grid_row_cut to be saved later
                offset_low = i_ * columnz_width          if i_ > 0 else 0                  # 0, 2, 5, 8 ...
                offset_high = offset_low + columnz_width if i_ > 0 else columnz_width     # 2, 5, 8, 11 ...
                print(i_, "X splitting at:", offset_low, offset_high)
                grid_row_cut = images.image_grid(aux_processed_res_images[offset_low:offset_high], rows=1, columnz=columnz_width)
                # processed_result.images.append(grid_row_cut) 
                processed.bski_splitter.imagez.append(grid_row_cut)
                processed.bski_splitter.promptz.append(processed.all_prompts[offset_low]) 
                processed.bski_splitter.seedz.append(processed.all_seeds[offset_low])  
                processed.bski_splitter.infotextz.append(processed.infotexts[offset_low]) 
                images.save_image(grid_row_cut, outpath_grids, "bski_grid", info=processed.infotexts[offset_low], extension=grid_format, prompt=processed.all_prompts[offset_low], seed=processed.all_seeds[offset_low], grid=True, p=processed)
        return processed
