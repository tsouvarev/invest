from httpxyz import Response
from lxml import etree

parser = etree.XMLParser(recover=True)


def select_one_from_response(response: Response, css_selector: str) -> str:
    nodes = select_many_from_response(response, [css_selector])

    try:
        node = nodes[0][0]
    except IndexError:
        return "-"

    return get_text_from_node(node)


def select_many_from_response(
    response: Response, css_selectors: list[str]
) -> list[str]:
    tree = etree.fromstring(response.text, parser)
    return list(zip(*map(tree.cssselect, css_selectors)))


def get_text_from_node(n) -> str:
    return n.text.strip()
