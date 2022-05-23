import cv2
import pytesseract
import numpy as np
from loguru import logger
import pdf2image
import requests
from piper.configurations import get_configuration

cfg = get_configuration()

def send_file_to_service(url, file_path):
    multipart_form_data = {
        'file': open(file_path, 'rb')
    }

    # print(multipart_form_data)
    # print((multipart_form_data.get('file')))
            
    return requests.post(url, files=multipart_form_data, verify=False)

def img_to_text(img, ts_conf):
    logger.info(f'pytesseract process file with len {len(img)}')
    txt_dict = pytesseract.image_to_data(
        img,
        lang=ts_conf.get('lang'),
        config=ts_conf.get('ts_config_row'),
        output_type=pytesseract.Output.DICT
    )
    return txt_dict


def bytes_handler(bbytes, suf, ts_conf):
    if suf in cfg.image_suffixes:
        logger.info('there are bytes a image')
        return img_bytes_handler(bbytes, ts_conf)
    elif suf in cfg.pdf_suffixes:
        logger.info('there are bytes a pdf document')
        return pdf_bytes_handler(bbytes, ts_conf)

    
def pdf_bytes_handler(pdf_bytes, ts_conf):
    bytes_to_images = pdf2image.convert_from_bytes(
        pdf_bytes,
        thread_count=cfg.thread_count,
        dpi=cfg.dpi
    )
    logger.info(f'pdf to image return {bytes_to_images} pages')
    pages = [np.asarray(x) for x in bytes_to_images]
    #TODO add processing all pages
    if len(pages) > 0:
        logger.error(f'try to recognize pages {len(pages)}')
        txt_dict = img_to_text(pages[0], ts_conf)
        logger.info(f'img_to_text returned {txt_dict}')
        return txt_dict
    else:
        logger.error('no pdf pages to recognize')


def img_bytes_handler(img_bytes, ts_conf):
    img = cv2.imdecode(np.asarray(bytearray(img_bytes), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        logger.info(f'processing img with shape {img.shape}')
        txt_dict = img_to_text(img, ts_conf)

        logger.info(f'get text from image {txt_dict}')
        logger.info(f'img_to_text returned {txt_dict}')
        return txt_dict

    else:
        logger.error('recive empty image or convertion failed')
