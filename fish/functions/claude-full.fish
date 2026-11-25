function claude-full --description 'Claude con MCP extra de ~/.claude/mcp-extra.json: todos o solo los grupos que pidas'
    # Por defecto cada sesión solo carga mysql-dev; el resto vive en ~/.claude/mcp-extra.json
    # (fuera de git: tiene credenciales). Un MCP no se puede cargar a media sesión: sal y
    # reabre con `claude-full <grupos> -c` para seguir la misma conversación.
    #
    #   claude-full                    todos los extra
    #   claude-full postgres -c        solo los Postgres kz-* dev, retomando la conversación
    #   claude-full postgres prod -r   varios grupos; lo que no es grupo se le pasa a claude
    #
    # Grupos: postgres (kz-* dev) · prod (mysql-prod, postgres-kibot-prod) · postman
    #         playwright · promotions (mysql-promotions-dev) · local (mysql-local) · all
    set -l known postgres prod postman playwright promotions local all
    set -l groups
    set -l rest
    set -l parsing 1
    for a in $argv
        if test $parsing = 1; and contains -- $a $known
            set -a groups $a
        else
            set parsing 0
            set -a rest $a
        end
    end

    set -l src ~/.claude/mcp-extra.json
    if not test -f $src
        echo "claude-full: no existe $src" >&2
        return 1
    end
    if test (count $groups) -eq 0; or contains -- all $groups
        claude --mcp-config $src $rest
        return
    end

    set -l names
    for g in $groups
        switch $g
            case postgres
                set -a names postgres-session-dev postgres-spatial-dev postgres-pricing-dev postgres-financial-dev postgres-hotpath-dev
            case prod
                set -a names mysql-prod postgres-kibot-prod
            case promotions
                set -a names mysql-promotions-dev
            case local
                set -a names mysql-local
            case '*'
                set -a names $g
        end
    end

    # El filtrado lleva credenciales: archivo privado en ~/.cache, nunca como argumento visible en ps.
    set -l dir ~/.cache/claude-mcp
    mkdir -p $dir
    chmod 700 $dir
    set -l out $dir/(string join - $groups).json
    set -l keep (printf '%s\n' $names | jq -R . | jq -sc .)
    touch $out
    chmod 600 $out
    jq --argjson keep $keep '{mcpServers: (.mcpServers | with_entries(select(.key as $k | $keep | index($k))))}' $src >$out
    or return 1
    claude --mcp-config $out $rest
end
