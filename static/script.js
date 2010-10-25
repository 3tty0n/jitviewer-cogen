
var glob_bridge_state = {};

function show_loop(no, path)
{
    glob_bridge_state.no = no;
    if (path) {
        glob_bridge_state.path = path;
    } else {
        delete glob_bridge_state.path;
    }
    $.getJSON('/loop', glob_bridge_state, function(arg) {
        $('#main').html(arg.html).ready(function() {
            $.scrollTo($('#line-' + arg.scrollto), 200);
        });
    });
}

function document_ready()
{
    var l = window.location.search.substr(1).split('&');
    for (var s in l) {
        var l2 = l[s].split('=', 2);
        var name = l2[0];
        var val = l2[1];
        if (name == 'show_loop') {
            show_loop(val);
        }
    }
}

function replace_from(elem, bridge_id)
{
    if (glob_bridge_state['loop-' + bridge_id]) {
        delete glob_bridge_state['loop-' + bridge_id];
    } else {
        glob_bridge_state['loop-' + bridge_id] = true;
    }
    $.getJSON('/loop', glob_bridge_state, function(res) {
        $('#main').html(res.html).ready(function() {
            for (var v in glob_bridge_state) {
                if (v.search('loop-') != -1) {
                    if (glob_bridge_state[v]) {
                        $('#' + v).next().html('&lt;&lt;hide bridge');
                    } else {
                        $('#' + v).next().html('&gt;&gt;show bridge');
                    }
                }
            }
            $.scrollTo($("#loop-" + bridge_id));
        });
    });
}