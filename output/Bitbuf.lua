local t5 = {__index = {}};
local String = function(a15) --[[ Line: 201 ]] --[[ Name: String ]]
    local v50 = math.ceil(a15.len / 32);
    local v51 = table.create(v50, "");
    for v52 in ipairs(v51) do
        if a15.buf[v52] then
            local v53 = string.pack("<I4", a15.buf[v52]);
            v51[v52] = v53;
        else
            v51[v52] = "\0\0\0\0";
        end
    end
    if 0 < a15.len % 32 then
        local v54 = ipairs(v51);
        local v55 = bit32.lshift(1, v54);
        local v56 = math.floor((a15.len - 1) / 8);
        local v57 = bit32.band(a15.buf[v50] or 0, v55 - 1);
        local v58 = string.pack("<I" .. v56 % 4 + 1, v57);
        v51[v50] = v58;
    end
    table.concat(v51);
    return;
end;
t5.__index.String = String;
local writeUnit = function(a16, b9, c5) --[[ Line: 229 ]] --[[ Name: writeUnit ]]
    if 0 <= b9 then
        if b9 > 32 then
        end
    end
    assert(false, "size must be in range [0,32]");
    if b9 == 0 then
        return;
    end
    local v59 = bit32.rshift(a16.i, 5);
    if a16.i % 32 == 0 then
        if b9 == 32 then
            local v60 = bit32.band(c5, 4294967295);
            a16.buf[v59 + 1] = v60;
        end
    elseif b9 - (32 - a16.i % 32) <= 0 then
        local v61 = bit32.replace(a16.buf[v59 + 1] or 0, c5, v59, b9);
        a16.buf[v59 + 1] = v61;
    else
        local v62 = bit32.extract(c5, 0, 32 - a16.i % 32);
        local v63 = bit32.replace(a16.buf[v59 + 1] or 0, v62, v59, 32 - a16.i % 32);
        a16.buf[v59 + 1] = v63;
        local v64 = bit32.extract(c5, 32 - a16.i % 32, b9 - (32 - a16.i % 32));
        local v65 = bit32.replace(a16.buf[v59 + 1 + 1] or 0, v64, 0, b9 - (32 - a16.i % 32));
        a16.buf[v59 + 1 + 1] = v65;
    end
    a16.i = a16.i + b9;
    if a16.len < a16.i then
        a16.len = a16.i;
    end
    return;
end;
t5.__index.writeUnit = writeUnit;
local readUnit = function(a17, b10) --[[ Line: 266 ]] --[[ Name: readUnit ]]
    if 0 <= b10 then
        if b10 > 32 then
        end
    end
    assert(false, "size must be in range [0,32]");
    if b10 == 0 then
        return 0;
    end
    local v66 = bit32.rshift(a17.i, 5);
    a17.i = a17.i + b10;
    if a17.len < a17.i then
        a17.len = a17.i;
    end
    if a17.i % 32 == 0 then
        if b10 == 32 then
            return a17.buf[v66 + 1] or 0;
        end
    end
    if 0 <= 32 - a17.i % 32 - b10 then
        local v67 = bit32.extract(a17.buf[v66 + 1] or 0, v66, b10);
        return v67;
    end
    local v68 = bit32.extract(a17.buf[v66 + 1 + 1] or 0, 0, -(32 - a17.i % 32 - b10));
    local v69 = bit32.extract(a17.buf[v66 + 1] or 0, v66, 32 - a17.i % 32);
    local v70 = bit32.lshift(v68, 32 - a17.i % 32);
    local v71 = bit32.bor(v69, v70);
    return v71;
end;
t5.__index.readUnit = readUnit;
local Len = function(a18) --[[ Line: 294 ]] --[[ Name: Len ]]
    return a18.len;
end;
t5.__index.Len = Len;
local SetLen = function(a19, b11) --[[ Line: 303 ]] --[[ Name: SetLen ]]
    if b11 < 0 then
    end
    if b11 < a19.len then
        local v72 = math.floor(b11 / 32);
        if b11 % 32 == 0 then
            a19.buf[v72 + 1] = nil;
        else
            local v73 = bit32.band(a19.buf[v72 + 1], 2 ^ (b11 % 32) - 1);
            a19.buf[v72 + 1] = v73;
        end
        local v74 = math.floor((a19.len - 1) / 32);
        for i5 = v74, 1, v72 + 1 + 1 do
            a19.buf[i5] = nil;
        end
    end
    a19.len = b11;
    if b11 < a19.i then
        a19.i = b11;
    end
    return;
end;
t5.__index.SetLen = SetLen;
local Index = function(a20) --[[ Line: 331 ]] --[[ Name: Index ]]
    return a20.i;
end;
t5.__index.Index = Index;
local SetIndex = function(a21, b12) --[[ Line: 339 ]] --[[ Name: SetIndex ]]
    if b12 < 0 then
    end
    a21.i = b12;
    if a21.len < b12 then
        a21.len = b12;
    end
    return;
end;
t5.__index.SetIndex = SetIndex;
local Fits = function(a22, b13) --[[ Line: 353 ]] --[[ Name: Fits ]]
    if type(b13) ~= "number" then
    end
    assert(true, "number expected");
    if b13 > a22.len - a22.i then
    end
    return true;
end;
t5.__index.Fits = Fits;
local WritePad = function(a25, b16) --[[ Line: 376 ]] --[[ Name: WritePad ]]
    -- upvalues: v87 (copy)
    if type(b16) ~= "number" then
    end
    assert(true, "number expected");
    if b16 <= 0 then
        return;
    end
    v87(a25, b16);
    return;
end;
t5.__index.WritePad = WritePad;
local v1 = function(a26, b17) --[[ Line: 388 ]] --[[ Name: ReadPad ]]
    if type(b17) ~= "number" then
    end
    assert(true, "number expected");
    if b17 <= 0 then
        return;
    end
    a26.i = a26.i + b17;
    if a26.len < a26.i then
        a26.len = a26.i;
    end
    return;
end;
t5.__index.ReadPad = v1;
local WriteAlign = function(a27, b18) --[[ Line: 401 ]] --[[ Name: WriteAlign ]]
    -- upvalues: v87 (copy)
    if type(b18) ~= "number" then
    end
    assert(true, "number expected");
    if b18 > 1 then
        if a27.i % b18 == 0 then
        end
    end
    return;
end;
t5.__index.WriteAlign = WriteAlign;
local v2 = function(a28, b19) --[[ Line: 414 ]] --[[ Name: ReadAlign ]]
    if type(b19) ~= "number" then
    end
    assert(true, "number expected");
    if b19 > 1 then
        if a28.i % b19 == 0 then
        end
    end
    return;
end;
t5.__index.ReadAlign = v2;
local v3 = function(a29) --[[ Line: 426 ]] --[[ Name: Reset ]]
    a29.i = 0;
    a29.len = 0;
    table.clear(a29.buf);
    return;
end;
t5.__index.Reset = v3;
local WriteBytes = function(a31, b21) --[[ Line: 468 ]] --[[ Name: WriteBytes ]]
    -- upvalues: v87 (copy)
    if type(b21) ~= "string" then
    end
    assert(true, "string expected");
    if b21 == "" then
        return;
    end
    if a31.i % 8 == 0 then
        v87(a31, b21);
        return;
    end
    for i8 = #b21, 1 do
        string.byte(b21, i8);
        a31:writeUnit();
    end
end;
t5.__index.WriteBytes = WriteBytes;
local v4 = function(a33, b23) --[[ Line: 529 ]] --[[ Name: ReadBytes ]]
    -- upvalues: v87 (copy)
    if type(b23) ~= "number" then
    end
    assert(true, "number expected");
    if b23 == 0 then
        return "";
    end
    if a33.i % 8 == 0 then
        v87(a33, b23);
        return;
    end
    for i10 = b23, 1 do
        a33:readUnit(8);
        local v98 = string.char();
        local v99 = table.create(b23, "");
        v99[i10] = v98;
    end
    local v100 = table.create(b23, "");
    b23(v100);
    return;
end;
t5.__index.ReadBytes = v4;
local WriteUint = function(a34, b24, c6) --[[ Line: 548 ]] --[[ Name: WriteUint ]]
    if type(b24) ~= "number" then
    end
    assert(true, "number expected");
    if type(c6) ~= "number" then
    end
    assert(true, "number expected");
    if 0 <= b24 then
        if b24 > 53 then
        end
    end
    assert(false, "size must be in range [0,53]");
    if b24 == 0 then
        return;
    end
    if b24 <= 32 then
        a34:writeUnit(b24, c6);
        return;
    end
    a34:writeUnit(32, c6);
    local v101 = math.floor(c6 % 2 ^ b24 / 4294967296);
    a34:writeUnit(b24 - 32, v101);
    return;
end;
t5.__index.WriteUint = WriteUint;
local v75 = function(a35, b25) --[[ Line: 567 ]] --[[ Name: ReadUint ]]
    if type(b25) ~= "number" then
    end
    assert(true, "number expected");
    if 0 <= b25 then
        if b25 > 53 then
        end
    end
    assert(false, "size must be in range [0,53]");
    if b25 == 0 then
        return 0;
    end
    if b25 <= 32 then
        a35:readUnit(b25);
        return;
    end
    local v102 = a35:readUnit(b25 - 32);
    local v103 = a35:readUnit(32);
    return v103 + v102 * 4294967296;
end;
t5.__index.ReadUint = v75;
local WriteBool = function(a36, b26) --[[ Line: 581 ]] --[[ Name: WriteBool ]]
    if b26 then
        a36:writeUnit(1, 1);
        return;
    end
    a36:writeUnit(1, 0);
    return;
end;
t5.__index.WriteBool = WriteBool;
local v80 = function(a37) --[[ Line: 593 ]] --[[ Name: ReadBool ]]
    if a37:readUnit(1) ~= 1 then
    end
    return true;
end;
t5.__index.ReadBool = v80;
local WriteByte = function(a38, b27) --[[ Line: 600 ]] --[[ Name: WriteByte ]]
    if type(b27) ~= "number" then
    end
    assert(true, "number expected");
    a38:writeUnit(8, b27);
    return;
end;
t5.__index.WriteByte = WriteByte;
local v81 = function(a39) --[[ Line: 608 ]] --[[ Name: ReadByte ]]
    a39:readUnit(8);
    return;
end;
t5.__index.ReadByte = v81;
local WriteInt = function(a40, b28, c7) --[[ Line: 616 ]] --[[ Name: WriteInt ]]
    if type(b28) ~= "number" then
    end
    assert(true, "number expected");
    if type(c7) ~= "number" then
    end
    assert(true, "number expected");
    if 0 <= b28 then
        if b28 > 53 then
        end
    end
    assert(false, "size must be in range [0,53]");
    if b28 == 0 then
        return;
    end
    if b28 <= 32 then
        a40:writeUnit(b28, c7);
        return;
    end
    a40:writeUnit(32, c7);
    local v104 = math.floor(c7 % 2 ^ b28 / 4294967296);
    a40:writeUnit(b28 - 32, v104);
    return;
end;
t5.__index.WriteInt = WriteInt;
local v82 = function(a41, b29) --[[ Line: 636 ]] --[[ Name: ReadInt ]]
    if type(b29) ~= "number" then
    end
    assert(true, "number expected");
    if 0 <= b29 then
        if b29 > 53 then
        end
    end
    assert(false, "size must be in range [0,53]");
    if b29 == 0 then
        return 0;
    end
    if b29 <= 32 then
        local v105 = a41:readUnit(b29);
    else
        local v106 = a41:readUnit(b29 - 32);
        local v107 = a41:readUnit(32);
    end
    if 2 ^ b29 / 2 <= nil % 2 ^ b29 then
        return nil % 2 ^ b29 - 2 ^ b29;
    end
    return nil % 2 ^ b29;
end;
t5.__index.ReadInt = v82;
local WriteCFrame = function(a42, b30) --[[ Line: 653 ]] --[[ Name: WriteCFrame ]]
    local v108 = b30:ToAxisAngle();
    local t6 = {b30.Position.X, b30.Position.Y, b30.Position.Z, v108.X, v108.Y, v108.Z, nil};
    for k, v109 in t6, nil, nil do
        a42:WriteFloat(32, v109);
    end
    return;
end;
t5.__index.WriteCFrame = WriteCFrame;
local v83 = function(a43) --[[ Line: 669 ]] --[[ Name: ReadCFrame ]]
    for i11 = 7, 1 do
        local v110 = a43:ReadFloat(32);
        local t7 = {};
        t7[i11] = v110;
    end
    local t8 = {};
    local v111 = Vector3.new(t8[4], t8[5], t8[6]);
    local v112 = 1(t8[1], t8[2], t8[3]);
    local v113 = CFrame.fromAxisAngle(v111, t8[7]);
    return v112 * v113;
end;
t5.__index.ReadCFrame = v83;
local WriteFloat = function(a44, b31, c8) --[[ Line: 687 ]] --[[ Name: WriteFloat ]]
    if type(b31) ~= "number" then
    end
    assert(true, "number expected");
    if type(c8) ~= "number" then
    end
    assert(true, "number expected");
    if b31 ~= 32 then
        if b31 ~= 64 then
        end
    end
    assert(true, "size must be 32 or 64");
    if b31 == 32 then
        string.pack("<f", c8);
        a44:WriteBytes();
        return;
    end
    string.pack("<d", c8);
    a44:WriteBytes();
    return;
end;
t5.__index.WriteFloat = WriteFloat;
local v84 = function(a45, b32) --[[ Line: 705 ]] --[[ Name: ReadFloat ]]
    if type(b32) ~= "number" then
    end
    assert(true, "number expected");
    if b32 ~= 32 then
        if b32 ~= 64 then
        end
    end
    assert(true, "size must be 32 or 64");
    if b32 == 32 then
        local v114 = a45:ReadBytes(b32 / 8);
        string.unpack("<f", v114);
        return;
    end
    local v115 = a45:ReadBytes(b32 / 8);
    string.unpack("<d", v115);
    return;
end;
t5.__index.ReadFloat = v84;
local WriteUfixed = function(a46, b33, c9, d) --[[ Line: 722 ]] --[[ Name: WriteUfixed ]]
    if type(b33) ~= "number" then
    end
    assert(true, "number expected");
    if type(c9) ~= "number" then
    end
    assert(true, "number expected");
    if 0 > b33 then
    end
    assert(true, "integer size must be >= 0");
    if 0 > c9 then
    end
    assert(true, "fractional size must be >= 0");
    if b33 + c9 > 53 then
    end
    assert(true, "combined size must be <= 53");
    if type(d) ~= "number" then
    end
    assert(true, "number expected");
    local v116 = math.floor(d * 2 ^ c9);
    a46:WriteUint(b33 + c9, v116 % 2 ^ (b33 + c9));
    return;
end;
t5.__index.WriteUfixed = WriteUfixed;
local v85 = function(a47, b34, c10) --[[ Line: 737 ]] --[[ Name: ReadUfixed ]]
    if type(b34) ~= "number" then
    end
    assert(true, "number expected");
    if type(c10) ~= "number" then
    end
    assert(true, "number expected");
    if 0 > b34 then
    end
    assert(true, "integer size must be >= 0");
    if 0 > c10 then
    end
    assert(true, "fractional size must be >= 0");
    if b34 + c10 > 53 then
    end
    assert(true, "combined size must be <= 53");
    local v117 = a47:ReadUint(b34 + c10);
    local v118 = math.floor(v117 % 2 ^ (b34 + c10));
    return v118 * 2 ^ -c10;
end;
t5.__index.ReadUfixed = v85;
local WriteFixed = function(a48, b35, c11, d2) --[[ Line: 751 ]] --[[ Name: WriteFixed ]]
    if type(b35) ~= "number" then
    end
    assert(true, "number expected");
    if type(c11) ~= "number" then
    end
    assert(true, "number expected");
    if 0 > b35 then
    end
    assert(true, "integer size must be >= 0");
    if 0 > c11 then
    end
    assert(true, "fractional size must be >= 0");
    if b35 + c11 > 53 then
    end
    assert(true, "combined size must be <= 53");
    if type(d2) ~= "number" then
    end
    assert(true, "number expected");
    local v119 = math.floor(d2 * 2 ^ c11);
    if 2 ^ (b35 + c11) / 2 <= v119 % 2 ^ (b35 + c11) then
    else
    end
    a48:WriteInt(b35 + c11, d2);
    return;
end;
t5.__index.WriteFixed = WriteFixed;
local v86 = function(a49, b36, c12) --[[ Line: 766 ]] --[[ Name: ReadFixed ]]
    if type(b36) ~= "number" then
    end
    assert(true, "number expected");
    if type(c12) ~= "number" then
    end
    assert(true, "number expected");
    if 0 > b36 then
    end
    assert(true, "integer size must be >= 0");
    if 0 > c12 then
    end
    assert(true, "fractional size must be >= 0");
    if b36 + c12 > 53 then
    end
    assert(true, "combined size must be <= 53");
    local v120 = a49:ReadInt(b36 + c12);
    if 2 ^ (b36 + c12) / 2 <= v120 % 2 ^ (b36 + c12) then
    else
    end
    local v121 = math.floor(b36 + c12);
    return v121 * 2 ^ -c12;
end;
t5.__index.ReadFixed = v86;
local t9 = {
    StringifyOnce = function(a11, b7) --[[ Line: 68 ]] --[[ Name: StringifyOnce ]]
        local v5 = math.ceil(a11 / 32);
        if 32 < a11 then
            error("Cant write > 32 bit size");
        end
        if a11 == 32 then
            local v6 = bit32.band(b7, 4294967295);
            local v7 = table.create(v5, 0);
            v7[1] = v6;
        elseif a11 - 32 <= 0 then
            local v8 = table.create(v5, 0);
            local v9 = bit32.replace(v8[1] or 0, b7, 0, a11);
            v8[1] = v9;
        else
            local v10 = table.create(v5, 0);
            local v11 = bit32.extract(b7, 0, 32);
            local v12 = bit32.replace(v10[1] or 0, v11, 0, 32);
            v10[1] = v12;
            local v13 = bit32.extract(b7, 32, a11 - 32);
            local v14 = bit32.replace(v10[2] or 0, v13, 0, a11 - 32);
            v10[2] = v14;
        end
        if v5 < 0 + a11 then
        end
        local v15 = math.ceil(v5 / 32);
        local v16 = table.create(v15, "");
        for v in ipairs(v16) do
            local v17 = table.create(v5, 0);
            if v17[v] then
                local v18 = string.pack("<I4", v17[v]);
                v16[v] = v18;
            else
                v16[v] = "\0\0\0\0";
            end
        end
        if 0 < v5 % 32 then
            local v19 = table.create(v5, 0);
            local v20 = ipairs(v16);
            local v21 = bit32.lshift(1, v20);
            local v22 = math.floor((v5 - 1) / 8);
            local v23 = bit32.band(v19[v15] or 0, v21 - 1);
            local v24 = string.pack("<I" .. v22 % 4 + 1, v23);
            v16[v15] = v24;
        end
        table.concat(v16);
        return;
    end,
    UnstringifyOnce = function(a12, b8) --[[ Line: 118 ]] --[[ Name: UnstringifyOnce ]]
        local v25 = math.ceil(#b8 / 4);
        local v26 = math.floor(#b8 / 4);
        for i = v26 - 1, 1, 0 do
            local v27 = string.byte(b8, i * 4 + 1, i * 4 + 4);
            local v28 = bit32.bor(v27, nil * 256, nil * 65536, nil * 16777216);
            local v29 = table.create(v25, 0);
            v29[i + 1] = v28;
        end
        for i2 = #b8 % 4 - 1, 1, 0 do
            local v30 = table.create(v25, 0);
            local v31 = string.byte(b8, (v25 - 1) * 4 + i2 + 1);
            local v32 = bit32.bor(v30[v25], v31 * 256 ^ i2);
            v30[v25] = v32;
        end
        return 0;
    end,
    new = function(a13) --[[ Line: 164 ]] --[[ Name: new ]]
        -- upvalues: v87 (copy)
        if a13 ~= nil then
            if type(a13) ~= "number" then
            end
        end
        assert(true, "number expected");
        local v41 = math.ceil((a13 or 0) / 32);
        local t = {buf = table.create(v41, 0), len = a13 or 0, i = 0};
        local v42 = setmetatable(v41, v87);
        return v42;
    end,
    fromString = function(a14) --[[ Line: 179 ]] --[[ Name: fromString ]]
        -- upvalues: v87 (copy)
        if type(a14) ~= "string" then
        end
        assert(true, "string expected");
        local v43 = math.ceil(#a14 / 4);
        local v44 = math.floor(#a14 / 4);
        for i3 = v44 - 1, 1, 0 do
            local t2 = {buf = table.create(v43, 0), len = #a14 * 8, i = 0};
            local v45 = string.byte(a14, i3 * 4 + 1, i3 * 4 + 4);
            local v46 = bit32.bor(v45, nil * 256, nil * 65536, nil * 16777216);
            t2.buf[i3 + 1] = v46;
        end
        for i4 = #a14 % 4 - 1, 1, 0 do
            local t3 = {buf = table.create(v43, 0), len = #a14 * 8, i = 0};
            local v47 = string.byte(a14, (v43 - 1) * 4 + i4 + 1);
            local v48 = bit32.bor(t3.buf[v43], v47 * 256 ^ i4);
            t3.buf[v43] = v48;
        end
        local t4 = {buf = table.create(v43, 0), len = #a14 * 8, i = 0};
        local v49 = setmetatable(t4, 0);
        return v49;
    end,
    isBuffer = function(a50) --[[ Line: 778 ]] --[[ Name: isBuffer ]]
        -- upvalues: v87 (copy)
        if getmetatable(a50) ~= v87 then
        end
        return true;
    end
};
return t9;
