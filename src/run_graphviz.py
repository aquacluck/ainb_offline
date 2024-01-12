from pprint import pp
import sys
import uuid

# Requires Graphviz installation and the graphviz Python package (pip install graphviz)
import graphviz
import orjson

from dt_tools.ainb import AINB


def graph(filepath):
    ainb = AINB(memoryview(open(filepath, "rb").read()))
    data = ainb.output_dict
    # TBbalance="min"?
    dot = graphviz.Digraph(
        data["Info"]["Filename"],
        graph_attr={"rankdir": "LR"},
        node_attr={"fontsize": "16", "fixedsize": "true", "shape": "box"}
    )

    precondition_nodes = []
    for node in data["Nodes"]:
        if "Flags" in node and "Is Precondition Node" in node["Flags"]:
            precondition_nodes.append(node["Node Index"])

    edge_list = []
    def iter_node(node_index: int, origin_id=None, already_seen=[], precon=False):
        node_index_str = str(node_index)

        if node_index not in already_seen and node_index < len(data["Nodes"]):
            #breakpoint()
            from random import randrange
            w = str(randrange(3) * 0.3 + 1.5)
            h = str(randrange(8) * 0.3 + 1.2)
            dot.attr("node", width=w, height=h)
            dot.node(node_index_str, node_index_str)

            if origin_id != None:
                if precon:
                    dot.edge(node_index_str, origin_id)
                    edge_list.append((node_index_str, origin_id))
                else:
                    dot.edge(origin_id, node_index_str)
                    edge_list.append((origin_id, node_index_str))
            already_seen.append(node_index)
            if "Precondition Nodes" in data["Nodes"][node_index]:
                for node in data["Nodes"][node_index]["Precondition Nodes"]:
                    iter_node(precondition_nodes[node], node_index_str, already_seen, precon=True)
            if "Input Parameters" in data["Nodes"][node_index]:
                for type in data["Nodes"][node_index]["Input Parameters"]:
                    for parameter in data["Nodes"][node_index]["Input Parameters"][type]:
                        if "Node Index" in parameter:
                            if parameter["Node Index"] >= 0:
                                iter_node(parameter["Node Index"], node_index_str, already_seen, precon=True)
                        elif "Sources" in parameter:
                            for param in parameter["Sources"]:
                                if param["Node Index"] >= 0:
                                    iter_node(param["Node Index"], node_index_str, already_seen, precon=True)
            if "Linked Nodes" in data["Nodes"][node_index]:
                if "Standard Link" in data["Nodes"][node_index]["Linked Nodes"]:
                    if data["Nodes"][node_index]["Node Type"] != "Element_Sequential":
                        for node in data["Nodes"][node_index]["Linked Nodes"]["Standard Link"]:
                                iter_node(node["Node Index"], node_index_str, already_seen)
                elif "Resident Update Link" in data["Nodes"][node_index]["Linked Nodes"]:
                    for node in data["Nodes"][node_index]["Linked Nodes"]["Resident Update Link"]:
                        iter_node(node["Node Index"], node_index_str, already_seen)
                elif "Output/bool Input/float Input Link" in data["Nodes"][node_index]["Linked Nodes"]:
                    for node in data["Nodes"][node_index]["Linked Nodes"]["Output/bool Input/float Input Link"]:
                        iter_node(node["Node Index"], node_index_str, already_seen, precon=True)
                elif "int Input Link" in data["Nodes"][node_index]["Linked Nodes"]:
                    for node in data["Nodes"][node_index]["Linked Nodes"]["int Input Link"]:
                        iter_node(node["Node Index"], node_index_str, already_seen, precon=True)
                elif "String Input Link" in data["Nodes"][node_index]["Linked Nodes"]:
                    for node in data["Nodes"][node_index]["Linked Nodes"]["String Input Link"]:
                        iter_node(node["Node Index"], node_index_str, already_seen, precon=True)
        else:
            if origin_id != None:
                if precon:
                    if ((node_index_str, origin_id)) not in edge_list:
                        dot.edge(node_index_str, origin_id)
                else:
                    if ((origin_id, node_index_str)) not in edge_list:
                        dot.edge(origin_id, node_index_str)

    if "Nodes" in data:
        if False and data["Info"]["File Category"] != "Logic" and "Commands" in data:
            # XXX unlinked nodes get completely lost here, but its ok, we don't want out-of-graph made up coords for those anyways?
            # also my changes caused even more to be unlinked oops. this is just a poc its ok :D
            for command in data["Commands"]:
                dot.attr('node', shape='diamond')
                cmd_id = f"Command[{command['Name']}]"
                dot.node(cmd_id, cmd_id)
                iter_node(command["Left Node Index"], cmd_id)
                if command["Right Node Index"] >= 0:
                    iter_node(command["Right Node Index"], cmd_id)
        else:
            for node in data["Nodes"]:
                node_id = iter_node(node["Node Index"])

    graphdump = orjson.loads(dot.pipe("json"))
    #pp(graphdump)
    #breakpoint()
    out = {}
    for obj in graphdump["objects"]:
        #print(f'{obj["name"]} {obj["pos"]}')
        node_index = int(obj["name"])
        x, y = obj["pos"].split(",")
        out[node_index] = int(float(x)), int(float(y))
    pp(out)

    svgfile = data["Info"]["Filename"]+".svg"
    # TODO kwarg directory=$TMP with tempdir, so its cleaned up on crash too
    dot.render(outfile=svgfile, format="svg", cleanup=True)
    print(f"\n(also wrote {svgfile})")


filepath = sys.argv[-1]
graph(filepath)
