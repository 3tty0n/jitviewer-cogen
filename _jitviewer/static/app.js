MainDisplay = can.Control({
    init: function(element, options){
        this.highlight_class = "variable_highlight";
    },
    "a[data-name] click": function(el, ev) {
        ev.preventDefault();
        var name = el.data('name');
        var path = el.data('path') || "";
        if(name) {
            can.route.attr({'name': name, 'path': path});
        }
    },
    ".operations a.inlined_call click": function(el, ev) {
        ev.preventDefault();
        var name = el.data('name');
        var path = el.data('path') || "";
        if(name) {
            can.route.attr({'name': name, 'path': path});
        }
    },
    ".operations a.bridgelink click": function(el, ev) {
        ev.preventDefault();
        var name = el.data('name');
        var path = el.data('path') || "";
        if(name) {
            can.route.attr({'name': name, 'path': path});
        }
    },
    ".operations .single-operation a click": function(el, ev) {
        ev.preventDefault();
        var name = el.data('name');
        var path = el.data('path') || "";
        if(name) {
            can.route.attr({'name': name, 'path': path});
        }
    },
    ".operations .single-operation span mouseenter": function(el, ev) {
        var name = el.data('name');
        if(name) {
            var s = '.operations .single-operation span[data-name="'+name+'"]';
            this.element.find(s).addClass(this.highlight_class);
        }
    },
    ".operations .single-operation span mouseleave": function(el, ev) {
        var name = el.data('name');
        if(name) {
            var s = '.operations .single-operation span[data-name="'+name+'"]';
            this.element.find(s).removeClass(this.highlight_class);
        }
    }
})
JITViewer = can.Control({
    init: function(element, options){
        this.state_asm = false;
        this.state_bytecodepos = false;
        this.state_op = true;
        this.current_line = null;
        this.filter_active = false;

        this.main_display = new MainDisplay(this.element.find("#main"), {})
        $("#inp-bar").focus();
    },
    'route': function() {
        //console.log('route index');
    },
    'items/:name route': function(data) {
        this.show_loop(data.name, data.path);
    },
    "#inp-bar focusin": function(el, ev){
        this.filter_active = true;
    },
    "#inp-bar focusout": function(el, ev){
        this.filter_active = false;
    },
    "#inp-bar keyup": function(el, ev){
        var v = el.val();
        $(".loopitem").each(function (i, l) {
            var name = $(l).attr('name');
            if(name.search(v) != -1){
                $(l).show();
            } else {
                $(l).hide();
            }
        });
    },
    toggle_asm: function(force_state) {
        if(typeof force_state !== 'undefined'){
            this.state_asm = force_state ? false : true;
        }

        var el = $("#asmtoggler");
        var asm = $(".asm");
        if(this.state_asm) {
            this.state_asm = false;
            el.html("Show assembler [a]");
            asm.hide();
        } else {
            this.state_asm = true;
            el.html("Hide assembler [a]");
            asm.show();
        }
    },
    "#asmtoggler click": function(el, ev) {
        ev.preventDefault();
        this.toggle_asm();
        return;
    },
    "#bytecodepos_toggler click": function(el, ev) {
        ev.preventDefault();
        this.toggle_bytecodepos();
        return;
    },
    toggle_bytecodepos: function(force_state){
        if(typeof force_state !== 'undefined'){
            this.state_bytecodepos = force_state ? false : true;
        }

        var el = $("#bytecodepos_toggler");
        var bytecodepos = $(".bytecodepos");
        if(this.state_bytecodepos) {
            this.state_bytecodepos = false;
            el.html("Show bytecode position [b]");
            bytecodepos.hide();
        } else {
            this.state_bytecodepos = true;
            el.html("Hide bytecode position [b]");
            bytecodepos.show();
        }
    },
    " keydown": function(el, ev){
        if(ev.keyCode == 13) {
            ev.preventDefault();
        }

        if(this.filter_active == false){
            if(ev.keyCode == 65){
                this.toggle_asm();
            } else if(ev.keyCode == 66){
                this.toggle_bytecodepos();
            } else if(ev.keyCode == 191){
                ev.preventDefault();
                $('#inp-bar').focus();
            }
        }
    },
    "#loops .loopitem a click": function(el, ev){
        ev.preventDefault();
        var name = el.data('name');
        var path = el.data('path') || "";
        console.log("loop:", name, path);
        if(name) {
            can.route.attr({'name': name, 'path': path});
        }
    },
    "#callstack a click": function(el, ev){
        ev.preventDefault();
        var name = el.data('name');
        var path = el.data('path') || "";
        if(name) {
            can.route.attr({'name': name, 'path': path});
        }
    },
    check_selfreferencing: function(){
        var self = this;
        var current_name = can.route.attr('name');
        var names = [];

        $.each(this.element.find('[data-name]'), function(idx, item){
            var name = String($(item).data('name'));
            if(name.indexOf('TargetToken') == -1) {
                token_name = 'TargetToken('+name+')';
            } else {
                token_name = name;
                name = token_name.replace('TargetToken(', '').replace(')', '');
            }

            if(current_name == name || current_name == token_name){
                names.push(name);
                names.push(token_name);
            }
        });
        unique_names = [];
        for(n in names){
            var name = names[n];
            if(unique_names.indexOf(name) == -1){
                unique_names.push(name);
            }
        }
        var elements = null;
        if(current_name == name){
            elements = self.element.find('.operations a[data-name="'+name+'"]');
            elements.css('color', 'black').append(' [self]');
        }
        if(current_name == token_name){
            elements = self.element.find('.operations a[data-name="'+token_name+'"]');
            elements.css('color', 'black').append(' [self]');
        }
    },
    show_loop: function(name, path){
        var self = this;
        var data = {
            'asm': this.state_asm,
            'bytecodepos': this.state_bytecodepos,
            'op': this.state_op,
            'name': name,
            'path': path
        }

        $.getJSON('/loop', data, function(arg) {
            $('#main').html(arg.html).ready(function() {
                var scrollto;
                if (arg.scrollto == 0) {
                    scrollto = 0;
                } else {
                    scrollto = arg.scrollto - 1;
                }
                $.scrollTo($('#line-' + scrollto), 200, {axis:'y'});
            });
            $('#callstack').html('')
            for (var index in arg.callstack) {
                var elem = arg.callstack[index];
                $('#callstack').append('<div><a href="#" data-name="' + name + '" data-path="' + elem[0] + '">' + elem[1] + "</a></div>");
            }

            self.toggle_asm(false);
            self.toggle_bytecodepos(false);

            self.check_selfreferencing();
        });
    }
})
