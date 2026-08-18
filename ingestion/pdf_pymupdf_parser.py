import camelot
import pymupdf

def extract_tables(path: str):
    tables = camelot.read_pdf(path, pages="1-15", flavor="lattice")

    #save bounding boxes for each page
    table_bboxes = {}
    table_data = [] #text of the tables

    for table in tables:
        page_num = table.page
        bbox = table._bbox  #PDF coordinates
        if page_num not in table_bboxes:
            table_bboxes[page_num] = []
        table_bboxes[page_num].append(bbox)

        #save content to dataframe
        table_data.append({
            "page": page_num,
            "data": table.df.to_dict(orient="records")
        })


    return table_bboxes, table_data


def extract_text(path: str, table_bboxes: dict):
    doc = pymupdf.open(path)

    for page_num in range(len(doc)):
        page = doc[page_num]

        #if no boxes, extract whole page
        if page_num + 1 not in table_bboxes:
            text = page.get_text()
            print(f"Page {page_num + 1}: {len(text)} chars")
            continue

        #if there are any boxes, extract only parts
        bboxes = table_bboxes[page_num + 1]

        #page dimensions
        page_rect = page.rect

        #sort boxes by y-position for filtering by table boxes
        bboxes.sort(key=lambda b: b[1])

        #extract text between tables
        text_parts = []
        current_y = page_rect.y0 #top of the page

        for bbox in bboxes:
            #extract text above the table
            if current_y < bbox[1]:
                clip_rect = pymupdf.Rect(page_rect.x0, current_y, page_rect.x1, bbox[1])
                text_above = page.get_text(clip=clip_rect)
                if text_above.strip():
                    text_parts.append(text_above)

            #skip table part, skip to the end of the table
            current_y = bbox[3]

        #extract text under the table
        if current_y < page_rect.y1:
            clip_rect = pymupdf.Rect(page_rect.x0, current_y, page_rect.x1, page_rect.y1)
            text_below = page.get_text(clip=clip_rect)
            if text_below.strip():
                text_parts.append(text_below)

        #join all the text
        page_text = "\n".join(text_parts)
        print("extracted text:", page_text)



if __name__ == "__main__":
    #"attention is all you need" paper
    pdf_path = "../data/raw/attention_is_all_you_need.pdf"


    table_bboxes, table_data = extract_tables(pdf_path)

    print("table bboxes",table_bboxes)
    print("table data", table_data)

    extract_text(pdf_path, table_bboxes)